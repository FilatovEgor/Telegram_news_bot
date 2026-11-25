"""Inspect and import the legacy SQLite ``motor`` table into PostgreSQL.

The input SQLite file is opened read-only and is never copied into this repository.
"""

import argparse
import asyncio
import sqlite3
import uuid
from collections import Counter
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.database.models import Article, NewsSource


def read_legacy_rows(path: Path) -> list[tuple]:
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        return connection.execute(
            "SELECT id, news_id, title, link, status, date FROM motor ORDER BY id"
        ).fetchall()
    finally:
        connection.close()


def inspect_legacy_rows(rows: list[tuple]) -> dict[str, int]:
    statuses = Counter((str(row[4]) if row[4] is not None else "<empty>") for row in rows)
    return dict(sorted(statuses.items()))


def map_legacy_status(value: str | None) -> str:
    # In the legacy handlers, Send meant that a draft was sent to the moderation chat.
    # Del and the failed-delete status both reflect an editor's request to reject the item.
    return {
        "Send": "SUMMARIZED",
        "Del": "REJECTED",
        "Can't del - more 48H": "REJECTED",
    }.get(value or "", "DISCOVERED")


async def import_rows(rows: list[tuple]) -> tuple[int, int]:
    settings = get_settings()
    engine = create_async_engine(settings.database_url_value, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    imported = skipped = 0
    try:
        async with session_factory() as session, session.begin():
            source = await session.scalar(
                select(NewsSource).where(NewsSource.source_key == "mrc")
            )
            if source is None:
                source = NewsSource(
                    source_key="mrc",
                    name="MRC",
                    kind="mrc",
                    base_url="https://www.mrc.ru",
                )
                session.add(source)
                await session.flush()

            for legacy_id, news_id, title, link, old_status, old_date in rows:
                if not news_id or not title or not link:
                    skipped += 1
                    continue

                legacy_status = str(old_status) if old_status is not None else None
                statement = (
                    insert(Article)
                    .values(
                        id=uuid.uuid4(),
                        source_id=source.id,
                        external_id=str(news_id),
                        canonical_url=str(link),
                        title=str(title),
                        content="",
                        content_hash=None,
                        status=map_legacy_status(legacy_status),
                        legacy_row_id=int(legacy_id) if legacy_id is not None else None,
                        legacy_status=legacy_status,
                        legacy_date=str(old_date) if old_date is not None else None,
                        source_metadata={"imported_from": "legacy_sqlite"},
                    )
                    .on_conflict_do_nothing(constraint="uq_article_source_external_id")
                    .returning(Article.id)
                )
                result = await session.execute(statement)
                if result.scalar_one_or_none() is None:
                    skipped += 1
                else:
                    imported += 1
    finally:
        await engine.dispose()
    return imported, skipped


async def main() -> None:
    parser = argparse.ArgumentParser(description="Import the old MRC SQLite archive into PostgreSQL")
    parser.add_argument("sqlite_path", type=Path, help="Path to a protected backup of storage.db")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the SQLite schema and report records/statuses without connecting to PostgreSQL",
    )
    args = parser.parse_args()
    if not args.sqlite_path.is_file():
        raise SystemExit(f"SQLite database not found: {args.sqlite_path}")

    try:
        rows = read_legacy_rows(args.sqlite_path)
    except sqlite3.Error as exc:
        raise SystemExit(f"Could not read legacy motor table: {exc}") from exc

    print(f"Legacy articles found: {len(rows)}")
    for status, count in inspect_legacy_rows(rows).items():
        print(f"  {status}: {count}")

    if args.dry_run:
        print("Dry run only; PostgreSQL was not modified.")
        return

    imported, skipped = await import_rows(rows)
    print(f"Imported: {imported}; skipped/already present/invalid: {skipped}")


if __name__ == "__main__":
    asyncio.run(main())
