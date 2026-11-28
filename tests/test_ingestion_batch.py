import os
import uuid

import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.models import Article, ArticleDuplicate, NewsSource
from app.repositories.articles import save_discovered_articles
from app.repositories.duplicates import record_duplicate_candidates_for_articles
from app.sources.base import SourceArticle
from app.sources.urls import normalized_content_hash


@pytest.mark.asyncio
async def test_batch_ingestion_and_duplicate_detection_use_bounded_round_trips():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for the PostgreSQL integration test")

    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    seed_source_id = uuid.uuid4()
    incoming_source_id = uuid.uuid4()
    seed_key = f"batch-seed-{seed_source_id.hex}"
    incoming_key = f"batch-incoming-{incoming_source_id.hex}"
    inserted_article_ids: list[uuid.UUID] = []
    query_count = 0

    def count_queries(_conn, _cursor, _statement, _parameters, _context, _executemany):
        nonlocal query_count
        query_count += 1

    event.listen(engine.sync_engine, "before_cursor_execute", count_queries)
    try:
        async with sessions() as session, session.begin():
            seed_source = NewsSource(
                id=seed_source_id,
                source_key=seed_key,
                name="Batch seed",
                kind="rss",
            )
            incoming_source = NewsSource(
                id=incoming_source_id,
                source_key=incoming_key,
                name="Batch incoming",
                kind="rss",
            )
            session.add_all([seed_source, incoming_source])
            await session.flush()
            session.add_all(
                [
                    Article(
                        id=uuid.uuid4(),
                        source_id=seed_source_id,
                        external_id="seed-exact",
                        canonical_url="https://example.com/story/exact",
                        title="An unrelated title for exact URL matching",
                        content="Original content",
                        source_metadata={},
                    ),
                    Article(
                        id=uuid.uuid4(),
                        source_id=seed_source_id,
                        external_id="seed-title",
                        canonical_url="https://example.com/story/title",
                        title="Central bank holds interest rates steady",
                        content="Central bank decision",
                        source_metadata={},
                    ),
                    Article(
                        id=uuid.uuid4(),
                        source_id=seed_source_id,
                        external_id="seed-hash",
                        canonical_url="https://example.com/story/hash",
                        title="A separate syndicated report",
                        content="A shared syndicated article body",
                        content_hash=normalized_content_hash("A shared syndicated article body"),
                        source_metadata={},
                    ),
                    Article(
                        id=uuid.uuid4(),
                        source_id=incoming_source_id,
                        external_id="same-source",
                        canonical_url="https://example.com/story/same-source",
                        title="Central bank keeps interest rates steady",
                        content="Same source articles are not cross-source duplicates",
                        source_metadata={},
                    ),
                ]
            )

        async with sessions() as session, session.begin():
            incoming_source = await session.get(NewsSource, incoming_source_id)
            assert incoming_source is not None
            new_articles = await save_discovered_articles(
                session,
                incoming_source,
                [
                    SourceArticle(
                        source_key=incoming_key,
                        external_id="incoming-exact",
                        url="https://example.com/story/exact",
                        title="A different title with the same canonical URL",
                        content="Different body",
                    ),
                    SourceArticle(
                        source_key=incoming_key,
                        external_id="incoming-title",
                        url="https://example.com/story/new-title",
                        title="Central bank keeps interest rates steady",
                        content="A new report about the central bank",
                    ),
                    SourceArticle(
                        source_key=incoming_key,
                        external_id="incoming-hash",
                        url="https://example.com/story/new-hash",
                        title="Another unrelated headline",
                        content="A shared syndicated article body",
                    ),
                    SourceArticle(
                        source_key=incoming_key,
                        external_id="incoming-title",
                        url="https://example.com/story/new-title",
                        title="Repeated feed entry",
                        content="This external ID should be ignored",
                    ),
                ],
            )
            assert len(new_articles) == 3
            inserted_article_ids = [article.id for article in new_articles]

        async with sessions() as session:
            new_articles = list(
                await session.scalars(
                    select(Article).where(Article.id.in_(inserted_article_ids))
                )
            )
            query_count = 0
            duplicate_count = await record_duplicate_candidates_for_articles(
                session,
                new_articles,
                similarity_threshold=0.75,
            )
            assert duplicate_count == 3
            assert query_count == 2  # one candidate SELECT and one bulk duplicate INSERT

            pairs = list(
                await session.scalars(
                    select(ArticleDuplicate).where(
                        ArticleDuplicate.article_id_left.in_(inserted_article_ids)
                        | ArticleDuplicate.article_id_right.in_(inserted_article_ids)
                    )
                )
            )
            assert {pair.match_type for pair in pairs} == {
                "canonical_url",
                "title_similarity",
                "content_hash",
            }
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count_queries)
        async with sessions() as session, session.begin():
            await session.execute(
                delete(Article).where(
                    Article.source_id.in_([seed_source_id, incoming_source_id])
                )
            )
            await session.execute(
                delete(NewsSource).where(
                    NewsSource.id.in_([seed_source_id, incoming_source_id])
                )
            )
        await engine.dispose()
