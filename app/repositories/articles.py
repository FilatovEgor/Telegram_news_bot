import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Article, NewsSource
from app.sources.base import SourceArticle
from app.sources.urls import canonicalize_url, normalized_content_hash


async def get_or_create_source(
    session: AsyncSession,
    source_key: str,
    name: str,
    kind: str,
    base_url: str | None = None,
) -> NewsSource:
    source = await session.scalar(select(NewsSource).where(NewsSource.source_key == source_key))
    if source is not None:
        source.name = name
        source.kind = kind
        source.base_url = base_url or source.base_url
        source.enabled = True
        await session.flush()
        return source
    source = NewsSource(source_key=source_key, name=name, kind=kind, base_url=base_url)
    session.add(source)
    await session.flush()
    return source


def _article_values(source: NewsSource, item: SourceArticle) -> dict[str, object]:
    canonical_url = canonicalize_url(item.url) or item.url
    return {
        "id": uuid.uuid4(),
        "source_id": source.id,
        "external_id": item.external_id,
        "canonical_url": canonical_url,
        "title": item.title,
        "content": item.content,
        "content_hash": normalized_content_hash(item.content),
        "source_published_at": item.published_at,
        "source_metadata": {"tags": item.tags, **item.metadata},
    }


async def save_discovered_articles(
    session: AsyncSession,
    source: NewsSource,
    items: list[SourceArticle],
) -> list[Article]:
    """Insert a source batch in one round trip, ignoring already-seen external IDs."""
    if not items:
        return []

    statement = (
        insert(Article)
        .values([_article_values(source, item) for item in items])
        .on_conflict_do_nothing(constraint="uq_article_source_external_id")
        .returning(Article)
    )
    result = await session.scalars(statement)
    return list(result.all())


async def save_discovered_article(
    session: AsyncSession,
    source: NewsSource,
    item: SourceArticle,
) -> uuid.UUID | None:
    statement = (
        insert(Article)
        .values(**_article_values(source, item))
        .on_conflict_do_nothing(constraint="uq_article_source_external_id")
        .returning(Article.id)
    )
    result = await session.execute(statement)
    return result.scalar_one_or_none()
