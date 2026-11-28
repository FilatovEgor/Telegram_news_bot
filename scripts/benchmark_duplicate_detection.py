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
            mutation = rng.choice(
                [
                    lambda value: value + " — подробности",
                    lambda value: value.replace("new ", "").replace("новые ", ""),
                    lambda value: value.replace("announces", "announced").replace("сохранил", "оставил"),
                    lambda value: value.upper(),
                    lambda value: re.sub(r"\s+", " ", value),
                ]
            )
            pairs.append(Pair(mutation(base), base, True))
        else:
            other = bases[(index + rng.randint(1, len(bases) - 1)) % len(bases)]
            pairs.append(Pair(base, other, False))
    return pairs


async def run(pairs_count: int) -> dict[str, object]:
    engine = create_async_engine(get_settings().database_url_value)
    pairs = make_pairs(pairs_count)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            await connection.execute(text("""
                CREATE TEMP TABLE duplicate_benchmark (
                    pair_id integer PRIMARY KEY,
                    candidate_title text NOT NULL
                ) ON COMMIT DROP
            """))
            await connection.execute(
                text("""
                    INSERT INTO duplicate_benchmark (pair_id, candidate_title)
                    VALUES (:pair_id, :candidate)
                """),
                [
                    {"pair_id": index, "candidate": pair.candidate}
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
            python_matches = {
                (incoming_index, candidate_index)
                for incoming_index, incoming in enumerate(pairs)
                for candidate_index, candidate in enumerate(pairs)
                if title_similarity(incoming.incoming, candidate.candidate) >= 0.92
            }
            python_wall_ms = (time.perf_counter() - python_start) * 1000
            python_cpu_ms = (time.process_time() - python_cpu_start) * 1000

            # LATERAL passes each incoming headline as a query parameter so the
            # inner lookup can use the GIN index instead of comparing two columns.
            pg_start = time.perf_counter()
            pg_cpu_start = time.process_time()
            rows = (
                await connection.execute(
                    text("""
                        WITH inputs AS (
                            SELECT title, ordinality::integer AS input_id
                            FROM unnest(CAST(:incoming_titles AS text[]))
                                 WITH ORDINALITY AS item(title, ordinality)
                        )
                        SELECT inputs.input_id, candidates.pair_id
                        FROM inputs
                        CROSS JOIN LATERAL (
                            SELECT pair_id
                            FROM duplicate_benchmark
                            WHERE lower(candidate_title) % lower(inputs.title)
                        ) AS candidates
                    """),
                    {"incoming_titles": [pair.incoming for pair in pairs]},
                )
            ).all()
            pg_wall_ms = (time.perf_counter() - pg_start) * 1000
            pg_cpu_ms = (time.process_time() - pg_cpu_start) * 1000
            retrieved = {(row.input_id - 1, row.pair_id) for row in rows}
            expected = {
                (index, index)
                for index, pair in enumerate(pairs)
                if pair.is_duplicate
            }
            python_expected = {
                (index, index)
                for index, pair in enumerate(pairs)
                if pair.is_duplicate
            }
            python_true_positives = python_matches & python_expected
            candidate_true_positives = expected & retrieved
            candidate_recall = (
                len(candidate_true_positives) / len(expected) if expected else 1.0
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
                    "candidate_comparisons": len(pairs) * len(pairs),
                    "matches": len(python_matches),
                    "precision": round(
                        len(python_true_positives) / len(python_matches), 4
                    ) if python_matches else 1.0,
                    "recall": round(
                        len(python_true_positives) / len(python_expected), 4
                    ) if python_expected else 1.0,
                },
                "pg_trgm_prefilter": {
                    "wall_ms": round(pg_wall_ms, 3),
                    "client_cpu_ms": round(pg_cpu_ms, 3),
                    "candidates": len(retrieved),
                    "candidate_recall": round(candidate_recall, 4),
                    "candidate_reduction_pct": round(
                        (1 - len(retrieved) / (len(pairs) * len(pairs))) * 100, 2
                    ) if pairs else 0.0,
                    "explain_analyze": explain,
                },
                "note": (
                    "Synthetic headline labels are generated, not human-reviewed production truth. "
                    "pg_trgm is a broad candidate prefilter, not a replacement for SequenceMatcher."
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
