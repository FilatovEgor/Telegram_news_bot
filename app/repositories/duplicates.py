import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Article, ArticleDuplicate
from app.sources.urls import title_similarity


async def record_duplicate_candidates(
    session: AsyncSession,
    article: Article,
    *,
    lookback_days: int = 30,
    similarity_threshold: float = 0.92,
    candidate_limit: int = 300,
) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    conditions = [Article.created_at >= cutoff]
    if article.canonical_url:
        conditions.append(Article.canonical_url == article.canonical_url)
    if article.content_hash:
        conditions.append(Article.content_hash == article.content_hash)

    result = await session.scalars(
        select(Article)
        .where(
            Article.id != article.id,
            Article.source_id != article.source_id,
            or_(*conditions),
        )
        .order_by(desc(Article.created_at))
        .limit(candidate_limit)
    )
    candidates = list(result)
    created = 0
    for candidate in candidates:
        if article.canonical_url == candidate.canonical_url:
            match_type, similarity = "canonical_url", 1.0
        elif article.content_hash and article.content_hash == candidate.content_hash:
            match_type, similarity = "content_hash", 1.0
        else:
            similarity = title_similarity(article.title, candidate.title)
            if similarity < similarity_threshold:
                continue
            match_type = "title_similarity"

        left_id, right_id = sorted((article.id, candidate.id), key=str)
        statement = (
            insert(ArticleDuplicate)
            .values(
                id=uuid.uuid4(),
                article_id_left=left_id,
                article_id_right=right_id,
                match_type=match_type,
                similarity=similarity,
                review_status="PENDING",
                details={
                    "left_title": article.title if left_id == article.id else candidate.title,
                    "right_title": candidate.title if right_id == candidate.id else article.title,
                },
            )
            .on_conflict_do_nothing(constraint="uq_article_duplicate_pair")
            .returning(ArticleDuplicate.id)
        )
        inserted = await session.execute(statement)
        created += int(inserted.scalar_one_or_none() is not None)
    return created
