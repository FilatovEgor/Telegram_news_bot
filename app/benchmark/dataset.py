from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class BenchmarkArticle:
    article_id: str
    title: str
    content: str
    source_url: str = ""
    tags: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: dict[str, Any], *, line_number: int) -> BenchmarkArticle:
        required = ("article_id", "title", "content")
        missing = [key for key in required if not isinstance(value.get(key), str) or not value[key].strip()]
        if missing:
            raise ValueError(f"JSONL line {line_number}: missing non-empty string fields: {', '.join(missing)}")
        tags = value.get("tags", [])
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise ValueError(f"JSONL line {line_number}: tags must be an array of strings")
        source_url = value.get("source_url", "")
        if not isinstance(source_url, str):
            raise ValueError(f"JSONL line {line_number}: source_url must be a string")
        return cls(value["article_id"].strip(), value["title"].strip(), value["content"].strip(), source_url.strip(), tuple(tags))

def load_dataset(path: str | Path, *, limit: int | None = None) -> list[BenchmarkArticle]:
    dataset_path = Path(path)
    if not dataset_path.is_file():
        raise FileNotFoundError(f"Benchmark dataset does not exist: {dataset_path}")
    articles: list[BenchmarkArticle] = []
    seen_ids: set[str] = set()
    with dataset_path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSONL line {line_number}: invalid JSON: {exc.msg}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"JSONL line {line_number}: each record must be a JSON object")
            article = BenchmarkArticle.from_mapping(value, line_number=line_number)
            if article.article_id in seen_ids:
                raise ValueError(f"JSONL line {line_number}: duplicate article_id {article.article_id!r}")
            seen_ids.add(article.article_id)
            articles.append(article)
            if limit is not None and len(articles) >= limit:
                break
    if not articles:
        raise ValueError(f"Benchmark dataset is empty: {dataset_path}")
    return articles
