from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.ai.agent import EditorialAgent
from app.ai.openai_provider import OpenAIProvider
from app.benchmark.dataset import load_dataset
from app.benchmark.pricing import ModelPricing
from app.benchmark.runner import BenchmarkRunner, write_results
from app.config import Settings


class OpenAISession:
    def __init__(self, model: str, settings: Settings) -> None:
        if settings.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is required to run the benchmark")
        if settings.ai_provider != "openai":
            raise ValueError("The benchmark CLI currently supports AI_PROVIDER=openai only")
        self._provider = OpenAIProvider(settings.model_copy(update={"openai_model": model}))
        self.agent = EditorialAgent(
            self._provider, max_tool_rounds=settings.ai_max_tool_rounds,
            retry_attempts=settings.ai_retry_attempts,
            retry_base_delay_seconds=settings.ai_retry_base_delay_seconds,
            request_timeout_seconds=settings.ai_request_timeout_seconds,
            run_timeout_seconds=settings.ai_run_timeout_seconds,
            max_input_chars=settings.ai_max_input_chars,
            max_completion_tokens_per_request=settings.ai_max_completion_tokens_per_request,
            max_completion_tokens_per_article=settings.ai_max_completion_tokens_per_article,
            max_summary_words=settings.ai_summary_max_words,
        )

    async def close(self) -> None:
        await self._provider.close()

def _load_pricing(path: str | None) -> dict[str, ModelPricing]:
    if path is None:
        return {}
    raw: Any = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Pricing file must contain a JSON object keyed by model name")
    pricing: dict[str, ModelPricing] = {}
    for model, values in raw.items():
        if not isinstance(values, dict):
            raise ValueError(f"Pricing for {model!r} must be an object")
        pricing[model] = ModelPricing(float(values["input_usd_per_million"]), float(values["output_usd_per_million"]))
    return pricing

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run fixed news inputs through OpenAI models; no Telegram publishing.")
    parser.add_argument("--dataset", required=True, help="JSONL dataset path")
    parser.add_argument("--models", default="gpt-6-luna", help="Comma-separated model IDs")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of articles")
    parser.add_argument("--output-dir", default="data/benchmark/runs", help="Directory for run artifacts")
    parser.add_argument("--pricing-json", default=None, help="Optional per-model token pricing JSON")
    return parser

async def _run(args: argparse.Namespace) -> Path:
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit must be positive")
    articles = load_dataset(args.dataset, limit=args.limit)
    models = [item.strip() for item in args.models.split(",") if item.strip()]
    if not models:
        raise ValueError("--models must contain at least one model ID")
    pricing = _load_pricing(args.pricing_json)
    # DATABASE_URL is required by application settings; no database connection is opened.
    settings = Settings(database_url="postgresql+asyncpg://benchmark:benchmark@localhost/benchmark")
    runner = BenchmarkRunner(lambda model: OpenAISession(model, settings), pricing=pricing)
    results = await runner.run(articles, models)
    destination = write_results(results, Path(args.output_dir) / results[0].run_id)
    print(f"Benchmark complete: {len(articles)} articles x {len(models)} models")
    print(f"Artifacts: {destination}")
    return destination

def main() -> None:
    args = build_parser().parse_args()
    try:
        asyncio.run(_run(args))
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f"Benchmark failed: {exc}") from exc

if __name__ == "__main__":
    main()
