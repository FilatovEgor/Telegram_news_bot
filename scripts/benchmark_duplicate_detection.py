"""Benchmark Python title matching against PostgreSQL pg_trgm candidate retrieval.

Uses an isolated temporary table and deterministic synthetic RU/EN headlines.
No production article data is read or modified.

Run after migrations:
    python -m scripts.benchmark_duplicate_detection --pairs 5000
"""

import argparse
import asyncio
import json
import random
import re
import statistics
import time
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.sources.urls import title_similarity


@dataclass(frozen=True)
class Pair:
    incoming: str
    candidate: str
    is_duplicate: bool


def make_pairs(count: int, seed: int = 417) -> list[Pair]:
    rng = random.Random(seed)
    english = [
        "Central bank keeps interest rates unchanged after policy meeting",
        "European Commission announces new digital markets regulation",
        "Technology company reports quarterly revenue growth",
        "Oil prices rise after latest OPEC production decision",
        "Government approves new energy infrastructure investment",
    ]
    russian = [
        "Центральный банк сохранил ключевую ставку без изменений",
        "Еврокомиссия представила новые правила цифровых рынков",
        "Технологическая компания сообщила о росте квартальной выручки",
        "Цены на нефть выросли после решения ОПЕК по добыче",
        "Правительство одобрило инвестиции в энергетическую инфраструктуру",
    ]
    bases = english + russian
    pairs: list[Pair] = []
    for index in range(count):
        base = bases[index % len(bases)]
        if rng.random() < 0.65:
            candidate = base
            incoming = base
            mutation = rng.choice(
                [
                    lambda value: value + " — подробности",
                    lambda value: value.replace("new ", "").replace("новые ", ""),
                    lambda value: value.replace("announces", "announced").replace("сохранил", "оставил"),
                    lambda value: value.upper(),
                    lambda value: re.sub(r"\s+", " ", value),
                ]
            )
            incoming = mutation(incoming)
            pairs.append(Pair(incoming, candidate, title_similarity(incoming, candidate) >= 0.92))
        else:
            other = bases[(index + rng.randint(1, len(bases) - 1)) % len(bases)]
            pairs.append(Pair(base, other, title_similarity(base, other) >= 0.92))
    return pairs


async def run(pairs_count: int) -> dict[str, object]:
    engine = create_async_engine(get_settings().database_url_value)
    pairs = make_pairs(pairs_count)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("""
                CREATE TEMP TABLE duplicate_benchmark (
                    pair_id integer PRIMARY KEY,
                    incoming_title text NOT NULL,
                    candidate_title text NOT NULL,
                    expected_duplicate boolean NOT NULL
                ) ON COMMIT DROP
            """))
            await connection.execute(
                text("""
                    INSERT INTO duplicate_benchmark
                    (pair_id, incoming_title, candidate_title, expected_duplicate)
                    VALUES (:pair_id, :incoming, :candidate, :expected)
                """),
                [
                    {
                        "pair_id": index,
                        "incoming": pair.incoming,
                        "candidate": pair.candidate,
                        "expected": pair.is_duplicate,
                    }
                    for index, pair in enumerate(pairs)
                ],
            )
            await connection.execute(text(
                "CREATE INDEX duplicate_benchmark_trgm "
                "ON duplicate_benchmark USING gin (lower(candidate_title) gin_trgm_ops)"
            ))
            await connection.execute(text("ANALYZE duplicate_benchmark"))

            python_start = time.perf_counter()
            python_cpu_start = time.process_time()
            python_matches = [
                index
                for index, pair in enumerate(pairs)
                if title_similarity(pair.incoming, pair.candidate) >= 0.92
            ]
            python_wall_ms = (time.perf_counter() - python_start) * 1000
            python_cpu_ms = (time.process_time() - python_cpu_start) * 1000

            # pg_trgm is deliberately a broad prefilter. The production Python
            # SequenceMatcher remains the final decision rule.
            pg_start = time.perf_counter()
            pg_cpu_start = time.process_time()
            rows = (
                await connection.execute(
                    text("""
                        SELECT pair_id, expected_duplicate
                        FROM duplicate_benchmark
                        WHERE lower(candidate_title) % lower(incoming_title)
                    """)
                )
            ).all()
            pg_wall_ms = (time.perf_counter() - pg_start) * 1000
            pg_cpu_ms = (time.process_time() - pg_cpu_start) * 1000
            pg_candidates = {row.pair_id for row in rows}
            expected = {i for i, pair in enumerate(pairs) if pair.is_duplicate}
            python_set = set(python_matches)
            # Evaluate candidate recall independently from final Python decisions.
            true_positive_candidates = expected & pg_candidates
            recall = len(true_positive_candidates) / len(expected) if expected else 1.0
            candidate_precision = (
                len(true_positive_candidates) / len(pg_candidates) if pg_candidates else 1.0
            )
            explain = (
                await connection.execute(
                    text("""
                        EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                        SELECT pair_id FROM duplicate_benchmark
                        WHERE lower(candidate_title) % lower(:title)
                    """),
                    {"title": pairs[0].incoming},
                )
            ).scalar_one()
            return {
                "pairs": len(pairs),
                "labelled_duplicates": len(expected),
                "python": {
                    "wall_ms": round(python_wall_ms, 3),
                    "cpu_ms": round(python_cpu_ms, 3),
                    "matches": len(python_set),
                    "precision": round(
                        len(python_set & expected) / len(python_set), 4
                    ) if python_set else 1.0,
                    "recall": round(len(python_set & expected) / len(expected), 4)
                    if expected else 1.0,
                },
                "pg_trgm_prefilter": {
                    "wall_ms": round(pg_wall_ms, 3),
                    "client_cpu_ms": round(pg_cpu_ms, 3),
                    "candidates": len(pg_candidates),
                    "candidate_precision": round(candidate_precision, 4),
                    "candidate_recall": round(recall, 4),
                    "explain_analyze": explain,
                },
                "note": (
                    "Synthetic labelled headline pairs only. pg_trgm candidate "
                    "retrieval is not a replacement for SequenceMatcher; inspect "
                    "candidate_recall before enabling the strategy."
                ),
            }
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=int, default=5000)
    args = parser.parse_args()
    if args.pairs < 1:
        parser.error("--pairs must be positive")
    print(json.dumps(asyncio.run(run(args.pairs)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
