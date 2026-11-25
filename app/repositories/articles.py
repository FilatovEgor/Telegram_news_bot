import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Article, NewsSource
from app.sources.base import SourceArticle


async def get_or_create_source(session: AsyncSession, source_key: str, name: str, kind: str, base_url: str | None = None) -> NewsSource:
    source = await session.scalar(select(NewsSource).where(NewsSource.source_key == source_key))
    if source is not None:
        source.name, source.kind, source.base_url, source.enabled = name, kind, base_url, True
        await session.flush()
        return source
    source = NewsSource(source_key=source_key, name=name, kind=kind, base_url=base_url)
    session.add(source)
    await session.flush()
    return source


async def save_discovered_article(session: AsyncSession, source: NewsSource, item: SourceArticle) -> bool:
    content_hash = hashlib.sha256(item.content.encode("utf-8")).hexdigest() if item.content.strip() else None
    statement = insert(Article).values(
        id=uuid.uuid4(), source_id=source.id, external_id=item.external_id,
        canonical_url=item.url, title=item.title, content=item.content,
        content_hash=content_hash, source_published_at=item.published_at,
        source_metadata={"tags": item.tags, **item.metadata},
    ).on_conflict_do_nothing(constraint="uq_article_source_external_id").returning(Article.id)
    result = await session.execute(statement)
    return result.scalar_one_or_none() is not None
