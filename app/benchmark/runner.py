from __future__ import annotations

import csv
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app.ai.agent import EditorialAgent
from app.benchmark.dataset import BenchmarkArticle
from app.benchmark.pricing import ModelPricing


class BenchmarkSession(Protocol):
    agent: EditorialAgent
    async def close(self) -> None: ...

SessionFactory = Callable[[str], BenchmarkSession]

@dataclass(slots=True)
class BenchmarkResult:
    run_id: str
    timestamp: str
    article_id: str
    model: str
    editorial_status: str
    translation_status: str
    input_tokens: int
    output_tokens: int
    attempts: int
    duration_ms: int
    estimated_cost_usd: float | None
    editorial_prompt_version: str | None
    translation_prompt_version: str | None
    editorial_output: dict[str, Any] | None
    translation_output: dict[str, Any] | None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

class BenchmarkRunner:
    """Runs the production editorial agent against fixed inputs; never publishes."""
    def __init__(self, session_factory: SessionFactory, *, pricing: dict[str, ModelPricing] | None = None) -> None:
        self._session_factory = session_factory
        self._pricing = pricing or {}

    async def run(self, articles: Sequence[BenchmarkArticle], models: Sequence[str]) -> list[BenchmarkResult]:
        if not articles:
            raise ValueError("At least one benchmark article is required")
        if not models or any(not model.strip() for model in models):
            raise ValueError("At least one non-empty model name is required")
        if len(set(models)) != len(models):
            raise ValueError("Model names must be unique")
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        results: list[BenchmarkResult] = []
        for model in models:
            session = self._session_factory(model)
            try:
                for article in articles:
                    results.append(await self._run_article(session.agent, article, model, run_id))
            finally:
                await session.close()
        return results

    async def _run_article(self, agent: EditorialAgent, article: BenchmarkArticle, model: str, run_id: str) -> BenchmarkResult:
        input_tokens = output_tokens = attempts = duration_ms = 0
        editorial_version = translation_version = None
        editorial_output = translation_output = None
        editorial_status = "error"
        translation_status = "not_applicable"
        error = None
        try:
            execution = await agent.create_editorial_package(article.title, article.content, article.source_url, list(article.tags))
            editorial_status = "success"
            editorial_output = execution.package.model_dump(mode="json")
            editorial_version = execution.prompt_version
            input_tokens += execution.input_tokens
            output_tokens += execution.output_tokens
            attempts += execution.attempt_count
            duration_ms += execution.duration_ms
            if execution.package.language.casefold() in {"ru", "russian"}:
                translation_status = "error"
                translated = await agent.create_translation_package(title=article.title, content=article.content, source_package=execution.package)
                translation_status = "success"
                translation_output = translated.package.model_dump(mode="json")
                translation_version = translated.prompt_version
                input_tokens += translated.input_tokens
                output_tokens += translated.output_tokens
                attempts += translated.attempt_count
                duration_ms += translated.duration_ms
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:500]}"
        pricing = self._pricing.get(model)
        return BenchmarkResult(
            run_id=run_id, timestamp=datetime.now(UTC).isoformat(), article_id=article.article_id,
            model=model, editorial_status=editorial_status, translation_status=translation_status,
            input_tokens=input_tokens, output_tokens=output_tokens, attempts=attempts,
            duration_ms=duration_ms,
            estimated_cost_usd=pricing.estimate(input_tokens, output_tokens) if pricing else None,
            editorial_prompt_version=editorial_version, translation_prompt_version=translation_version,
            editorial_output=editorial_output, translation_output=translation_output, error=error,
        )

def write_results(results: Sequence[BenchmarkResult], output_dir: str | Path) -> Path:
    if not results:
        raise ValueError("There are no benchmark results to write")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / "results.jsonl").open("w", encoding="utf-8") as stream:
        for result in results:
            stream.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")
    metric_fields = ["run_id", "timestamp", "article_id", "model", "editorial_status", "translation_status", "input_tokens", "output_tokens", "attempts", "duration_ms", "estimated_cost_usd", "editorial_prompt_version", "translation_prompt_version", "error"]
    with (destination / "metrics.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=metric_fields)
        writer.writeheader()
        for result in results:
            row = result.to_dict()
            writer.writerow({key: row[key] for key in metric_fields})
    review_fields = ["article_id", "model", "factual_accuracy_1_5", "completeness_1_5", "hallucination_1_5", "editorial_quality_1_5", "translation_fidelity_1_5", "critical_hallucination", "human_accepted", "reviewer_notes"]
    with (destination / "human_review.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=review_fields)
        writer.writeheader()
        for result in results:
            writer.writerow({"article_id": result.article_id, "model": result.model})
    return destination
