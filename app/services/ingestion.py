import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.database.models import Article, NewsSource, SourceRun
from app.repositories.articles import get_or_create_source, save_discovered_article
from app.repositories.duplicates import record_duplicate_candidates
from app.sources.base import NewsSource as NewsSourceAdapter, SourceFetchResult

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class IngestionResult:
    sources_checked: int
    discovered: int
    created: int
    duplicates: int = 0
    failures: int = 0


@dataclass(slots=True, frozen=True)
class SourceHealth:
    source_key: str
    name: str
    status: str | None
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    consecutive_failures: int
    last_duration_ms: int | None
    last_fetched_count: int
    last_error: str | None


class IngestionService:
    def __init__(
        self,
        sources: list[NewsSourceAdapter],
        session_factory: async_sessionmaker,
        settings: Settings | None = None,
    ) -> None:
        self._sources = sources
        self._session_factory = session_factory
        self._settings = settings

    async def ingest(self, limit: int = 50) -> IngestionResult:
        checked = discovered = created = duplicates = failures = 0
        for adapter in self._sources:
            checked += 1
            started_at = datetime.now(UTC)
            started_clock = time.monotonic()
            fetch_error: Exception | None = None
            fetch_result = SourceFetchResult()

            try:
                raw_result = await adapter.fetch_latest(limit=limit)
                if isinstance(raw_result, SourceFetchResult):
                    fetch_result = raw_result
                else:
                    articles = list(raw_result)
                    fetch_result = SourceFetchResult(
                        articles=articles,
                        attempted_count=len(articles),
                    )
            except Exception as exc:
                fetch_error = exc
                logger.warning(
                    "News source fetch failed: %s (%s)",
                    adapter.key,
                    type(exc).__name__,
                )

            duration_ms = max(0, int((time.monotonic() - started_clock) * 1000))
            finished_at = datetime.now(UTC)
            discovered += fetch_result.fetched_count
            failures += max(1, fetch_result.failed_count) if fetch_error else fetch_result.failed_count
            source_created = source_duplicates = 0
            base_url = getattr(adapter, "base_url", "") or None
            kind = getattr(adapter, "kind", "rss")

            async with self._session_factory() as session, session.begin():
                source = await get_or_create_source(
                    session,
                    adapter.key,
                    adapter.name,
                    kind,
                    base_url,
                )
                if fetch_error is None:
                    for item in fetch_result.articles:
                        article_id = await save_discovered_article(session, source, item)
                        if article_id is None:
                            continue
                        source_created += 1
                        article = await session.get(Article, article_id)
                        if article is not None:
                            source_duplicates += await record_duplicate_candidates(
                                session,
                                article,
                                lookback_days=self._settings.duplicate_lookback_days if self._settings else 30,
                                similarity_threshold=(
                                    self._settings.duplicate_title_similarity_threshold
                                    if self._settings else 0.92
                                ),
                                candidate_limit=(
                                    self._settings.duplicate_candidate_limit if self._settings else 300
                                ),
                            )

                if fetch_error is not None:
                    status = "FAILED"
                    error_text = type(fetch_error).__name__
                    source.consecutive_failures += 1
                else:
                    status = "PARTIAL" if fetch_result.failed_count or fetch_result.warnings else "SUCCESS"
                    error_text = "; ".join(fetch_result.warnings)[:1000] or None
                    source.consecutive_failures = 0
                    source.last_success_at = finished_at

                source.last_status = status
                source.last_attempt_at = started_at
                source.last_duration_ms = duration_ms
                source.last_fetched_count = fetch_result.fetched_count
                source.last_error = error_text
                session.add(
                    SourceRun(
                        source_id=source.id,
                        status=status,
                        started_at=started_at,
                        finished_at=finished_at,
                        duration_ms=duration_ms,
                        attempted_count=fetch_result.attempted_count,
                        fetched_count=fetch_result.fetched_count,
                        failed_count=(
                            fetch_result.failed_count if fetch_error is None
                            else max(1, fetch_result.failed_count)
                        ),
                        created_count=source_created,
                        duplicate_count=source_duplicates,
                        error_text=error_text,
                        warnings=fetch_result.warnings,
                    )
                )
            created += source_created
            duplicates += source_duplicates

        return IngestionResult(checked, discovered, created, duplicates, failures)

    async def source_health(self) -> list[SourceHealth]:
        async with self._session_factory() as session:
            sources = await session.scalars(
                select(NewsSource).order_by(NewsSource.source_key)
            )
            return [
                SourceHealth(
                    source_key=source.source_key,
                    name=source.name,
                    status=source.last_status,
                    last_attempt_at=source.last_attempt_at,
                    last_success_at=source.last_success_at,
                    consecutive_failures=source.consecutive_failures,
                    last_duration_ms=source.last_duration_ms,
                    last_fetched_count=source.last_fetched_count,
                    last_error=source.last_error,
                )
                for source in sources
            ]
