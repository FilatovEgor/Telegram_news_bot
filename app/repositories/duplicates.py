import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import column, desc, func, or_, select, values
from sqlalchemy.dialects.postgresql import TEXT, UUID as PG_UUID, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Article, ArticleDuplicate
from app.sources.urls import title_similarity, title_trigram_text

_DUPLICATE_INSERT_BATCH_SIZE = 500
_TRIGRAM_CANDIDATE_BATCH_SIZE = 100


async def _load_title_candidates(
    session: AsyncSession,
    articles: list[Article],
    *,
    cutoff: datetime,
    source_ids: set[uuid.UUID],
    similarity_threshold: float,
    candidate_limit: int,
) -> dict[uuid.UUID, list[Article]]:
    """Shortlist with pg_trgm; SequenceMatcher remains the final similarity decision."""
    matches: dict[uuid.UUID, list[Article]] = {article.id: [] for article in articles}
    prefilter_threshold = max(0.1, similarity_threshold - 0.15)

    for offset in range(0, len(articles), _TRIGRAM_CANDIDATE_BATCH_SIZE):
        chunk = articles[offset : offset + _TRIGRAM_CANDIDATE_BATCH_SIZE]
        incoming_rows = values(
            column("article_id", PG_UUID(as_uuid=True)),
            column("normalized_title", TEXT),
            name="incoming_titles",
        ).data([
            (article.id, title_trigram_text(article.title))
            for article in chunk
        ])
        incoming = incoming_rows.cte("incoming_titles")
        statement = (
            select(incoming.c.article_id, Article)
            .select_from(
                incoming.join(
                    Article,
                    func.lower(Article.title).bool_op("%")(incoming.c.normalized_title),
                )
            )
            .where(
                Article.created_at >= cutoff,
                Article.source_id.notin_(source_ids),
            )
            .order_by(desc(Article.created_at))
        )
        rows = (await session.execute(statement)).all()
        counts = {article.id: 0 for article in chunk}
        for article_id, candidate in rows:
            if counts.get(article_id, candidate_limit) < candidate_limit:
                matches[article_id].append(candidate)
                counts[article_id] += 1
    return matches


async def record_duplicate_candidates_for_articles(
    session: AsyncSession,
    articles: list[Article],
    *,
    lookback_days: int = 30,
    similarity_threshold: float = 0.92,
    candidate_limit: int = 300,
) -> int:
    """Record exact and fuzzy cross-source duplicate suggestions for new articles."""
    if not articles:
        return 0

    source_ids = {article.source_id for article in articles}
    cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
    exact_conditions = [
        Article.canonical_url.in_({article.canonical_url for article in articles})
    ]
    hashes = {article.content_hash for article in articles if article.content_hash}
    if hashes:
        exact_conditions.append(Article.content_hash.in_(hashes))
    exact_result = await session.scalars(
        select(Article)
        .where(
            Article.created_at >= cutoff,
            Article.source_id.notin_(source_ids),
            or_(*exact_conditions),
        )
        .order_by(desc(Article.created_at))
    )
    exact_candidates = list(exact_result)
    title_candidates = await _load_title_candidates(
        session,
        articles,
        cutoff=cutoff,
        source_ids=source_ids,
        similarity_threshold=similarity_threshold,
        candidate_limit=candidate_limit,
    )

    duplicate_rows: dict[tuple[uuid.UUID, uuid.UUID], dict[str, object]] = {}
    for article in articles:
        candidates_by_id = {candidate.id: candidate for candidate in exact_candidates}
        candidates_by_id.update({
            candidate.id: candidate for candidate in title_candidates[article.id]
        })
        for candidate in candidates_by_id.values():
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
