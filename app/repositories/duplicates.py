import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Article, ArticleDuplicate
from app.sources.urls import title_similarity

_DUPLICATE_INSERT_BATCH_SIZE = 500


async def record_duplicate_candidates_for_articles(
    session: AsyncSession,
    articles: list[Article],
    *,
    lookback_days: int = 30,
    similarity_threshold: float = 0.92,
    candidate_limit: int = 300,
) -> int:
    """Compare a batch of new articles with one bounded cross-source candidate set."""
    if not articles:
        return 0

    source_ids = {article.source_id for article in articles}
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    result = await session.scalars(
        select(Article)
        .where(
            Article.created_at >= cutoff,
            Article.source_id.notin_(source_ids),
        )
        .order_by(desc(Article.created_at))
        .limit(candidate_limit)
    )
    candidates = list(result)

    duplicate_rows: dict[tuple[uuid.UUID, uuid.UUID], dict[str, object]] = {}
    for article in articles:
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
            duplicate_rows[(left_id, right_id)] = {
                "id": uuid.uuid4(),
                "article_id_left": left_id,
                "article_id_right": right_id,
                "match_type": match_type,
                "similarity": similarity,
                "review_status": "PENDING",
                "details": {
                    "left_title": article.title if left_id == article.id else candidate.title,
                    "right_title": candidate.title if right_id == candidate.id else article.title,
                },
            }

    rows = list(duplicate_rows.values())
    created = 0
    for offset in range(0, len(rows), _DUPLICATE_INSERT_BATCH_SIZE):
        statement = (
            insert(ArticleDuplicate)
            .values(rows[offset : offset + _DUPLICATE_INSERT_BATCH_SIZE])
            .on_conflict_do_nothing(constraint="uq_article_duplicate_pair")
            .returning(ArticleDuplicate.id)
        )
        inserted = await session.scalars(statement)
        created += len(inserted.all())
    return created


async def record_duplicate_candidates(
    session: AsyncSession,
    article: Article,
    *,
    lookback_days: int = 30,
    similarity_threshold: float = 0.92,
    candidate_limit: int = 300,
) -> int:
    """Backward-compatible single-article wrapper."""
    return await record_duplicate_candidates_for_articles(
        session,
        [article],
        lookback_days=lookback_days,
        similarity_threshold=similarity_threshold,
        candidate_limit=candidate_limit,
    )
