import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import Settings
from app.database.models import Article, NewsSource
from app.services.editorial import EditorialService
from app.services.pagination import decode_cursor, encode_cursor


def test_pagination_cursor_round_trips_timestamp_and_uuid():
    created_at = datetime(2026, 11, 28, 12, 34, 56, 123456, tzinfo=UTC)
    row_id = uuid.uuid4()

    decoded = decode_cursor(encode_cursor(created_at, row_id))

    assert decoded == (created_at, row_id)


@pytest.mark.parametrize("cursor", ["", "not-a-cursor", "YQ"])
def test_invalid_pagination_cursor_is_rejected(cursor: str):
    with pytest.raises(ValueError, match="Invalid pagination cursor"):
        decode_cursor(cursor)


@pytest.mark.asyncio
async def test_pending_article_pages_are_bounded_stable_and_navigable():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for the PostgreSQL integration test")

    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    source_id = uuid.uuid4()
    source_key = f"pagination-test-{source_id.hex}"
    article_ids = [uuid.uuid4() for _ in range(5)]
    base_time = datetime(2026, 11, 28, 10, 0, tzinfo=UTC)
    try:
        async with sessions() as session, session.begin():
            session.add(
                NewsSource(
                    id=source_id,
                    source_key=source_key,
                    name="Pagination test source",
                    kind="rss",
                )
            )
            for index, article_id in enumerate(article_ids):
                session.add(
                    Article(
                        id=article_id,
                        source_id=source_id,
                        external_id=f"pagination-{index}",
                        canonical_url=f"https://example.com/pagination/{index}",
                        title=f"Pagination article {index}",
                        content="Test content",
                        source_metadata={},
                        created_at=base_time + timedelta(seconds=index),
                    )
                )

        service = EditorialService(
            agent=None,
            session_factory=sessions,
            settings=Settings(database_url=database_url),
        )
        first = await service.pending_articles_page(limit=2)
        second = await service.pending_articles_page(limit=2, cursor=first.next_cursor)
        third = await service.pending_articles_page(limit=2, cursor=second.next_cursor)
        back_to_second = await service.pending_articles_page(
            limit=2,
            cursor=third.previous_cursor,
            direction="previous",
        )

        assert [item.id for item in first.items] == article_ids[:2]
        assert [item.id for item in second.items] == article_ids[2:4]
        assert [item.id for item in third.items] == article_ids[4:]
        assert first.previous_cursor is None
        assert first.next_cursor is not None
        assert second.previous_cursor is not None
        assert second.next_cursor is not None
        assert third.next_cursor is None
        assert [item.id for item in back_to_second.items] == article_ids[2:4]
        assert back_to_second.next_cursor is not None
        assert back_to_second.previous_cursor is not None
    finally:
        async with sessions() as session, session.begin():
            await session.execute(delete(Article).where(Article.id.in_(article_ids)))
            await session.execute(delete(NewsSource).where(NewsSource.id == source_id))
        await engine.dispose()
