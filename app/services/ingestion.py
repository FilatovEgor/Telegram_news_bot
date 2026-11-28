import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Settings
from app.database.models import NewsSource, SourceRun
from app.repositories.articles import get_or_create_source, save_discovered_articles
from app.repositories.duplicates import record_duplicate_candidates_for_articles
from app.sources.base import NewsSource as NewsSourceAdapter
from app.sources.base import SourceArticle, SourceFetchResult

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


@dataclass(slots=True, frozen=True)
class _FetchedSource:
    result: SourceFetchResult
    error: Exception | None
    started_at: datetime
    finished_at: datetime
    duration_ms: int


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

    async def _fetch_sources(self, limit: int) -> list[_FetchedSource]:
        """Fetch sources concurrently, but keep results in configured source order."""
        concurrency = (
            self._settings.source_fetch_concurrency if self._settings else 4
        )
        semaphore = asyncio.Semaphore(concurrency)

        async def fetch_one(adapter: NewsSourceAdapter) -> _FetchedSource:
            async with semaphore:
                started_at = datetime.now(UTC)
                started_clock = time.monotonic()
                try:
                    raw_result = await adapter.fetch_latest(limit=limit)
                    if isinstance(raw_result, SourceFetchResult):
                        result = raw_result
                    else:
                        articles = list(raw_result)
                        result = SourceFetchResult(
                            articles=articles,
                            attempted_count=len(articles),
                        )
                    error = None
                except Exception as exc:
                    result = SourceFetchResult()
                    error = exc
                    logger.warning(
                        "News source fetch failed: %s (%s)",
                        adapter.key,
                        type(exc).__name__,
                    )
                finished_at = datetime.now(UTC)
                duration_ms = max(
                    0, int((time.monotonic() - started_clock) * 1000)
                )
                return _FetchedSource(
                    result=result,
                    error=error,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=duration_ms,
                )

        return await asyncio.gather(
            *(fetch_one(adapter) for adapter in self._sources)
        )

    def _persist_batch_size(self) -> int:
        return (
            self._settings.source_persist_batch_size
            if self._settings else 100
        )

    async def _persist_article_chunk(
        self,
        adapter: NewsSourceAdapter,
        articles: list[SourceArticle],
    ) -> tuple[int, int]:
        """Persist one bounded chunk in a short, self-contained transaction."""
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
            new_articles = await save_discovered_articles(
                session,
                source,
                articles,
            )
            duplicate_count = await record_duplicate_candidates_for_articles(
                session,
                new_articles,
                lookback_days=(
                    self._settings.duplicate_lookback_days if self._settings else 30
                ),
                similarity_threshold=(
                    self._settings.duplicate_title_similarity_threshold
                    if self._settings else 0.92
                ),
                candidate_limit=(
                    self._settings.duplicate_candidate_limit if self._settings else 300
                ),
            )
            return len(new_articles), duplicate_count

    async def _record_source_run(
        self,
        adapter: NewsSourceAdapter,
        fetched: _FetchedSource,
        *,
        created: int,
        duplicates: int,
        persistence_error: Exception | None = None,
    ) -> None:
        base_url = getattr(adapter, "base_url", "") or None
        kind = getattr(adapter, "kind", "rss")
        fetch_result = fetched.result
        failed_count = fetch_result.failed_count
        error_parts = list(fetch_result.warnings)

        if fetched.error is not None:
            failed_count = max(1, failed_count)
            error_parts.append(type(fetched.error).__name__)
        if persistence_error is not None:
            failed_count += 1
            error_parts.append(f"persistence: {type(persistence_error).__name__}")

        if fetched.error is not None:
            status = "FAILED"
        elif persistence_error is not None:
            status = "PARTIAL" if created else "FAILED"
        elif fetch_result.failed_count or fetch_result.warnings:
            status = "PARTIAL"
        else:
            status = "SUCCESS"

        error_text = "; ".join(error_parts)[:1000] or None
        finished_at = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            source = await get_or_create_source(
                session,
                adapter.key,
                adapter.name,
                kind,
                base_url,
            )
            if status == "SUCCESS" or status == "PARTIAL" and fetched.error is None:
                source.consecutive_failures = 0
                source.last_success_at = fetched.finished_at
            else:
                source.consecutive_failures += 1

            source.last_status = status
            source.last_attempt_at = fetched.started_at
            source.last_duration_ms = fetched.duration_ms
            source.last_fetched_count = fetch_result.fetched_count
            source.last_error = error_text
            session.add(
                SourceRun(
                    source_id=source.id,
                    status=status,
                    started_at=fetched.started_at,
                    finished_at=finished_at,
                    duration_ms=fetched.duration_ms,
                    attempted_count=fetch_result.attempted_count,
                    fetched_count=fetch_result.fetched_count,
                    failed_count=failed_count,
                    created_count=created,
                    duplicate_count=duplicates,
                    error_text=error_text,
                    warnings=fetch_result.warnings,
                )
            )

    async def ingest(self, limit: int = 50) -> IngestionResult:
        run_started = time.monotonic()
        checked = discovered = created = duplicates = failures = 0
        fetched_sources = await self._fetch_sources(limit)

        # Fetches run concurrently, but persistence remains sequential per source.
        # Every chunk has its own transaction; no AsyncSession is shared.
        for adapter, fetched in zip(self._sources, fetched_sources, strict=True):
            checked += 1
            fetch_result = fetched.result
            discovered += fetch_result.fetched_count
            source_created = source_duplicates = 0
            persistence_error: Exception | None = None

            if fetched.error is None:
                batch_size = self._persist_batch_size()
                for offset in range(0, len(fetch_result.articles), batch_size):
                    chunk = fetch_result.articles[offset : offset + batch_size]
                    try:
                        chunk_created, chunk_duplicates = await self._persist_article_chunk(
                            adapter,
                            chunk,
                        )
                    except Exception as exc:
                        persistence_error = exc
                        logger.exception(
                            "News source persistence failed: %s chunk_start=%d",
                            adapter.key,
                            offset,
                        )
                        break
                    source_created += chunk_created
                    source_duplicates += chunk_duplicates

            await self._record_source_run(
                adapter,
                fetched,
                created=source_created,
                duplicates=source_duplicates,
                persistence_error=persistence_error,
            )
            created += source_created
            duplicates += source_duplicates
            failures += fetch_result.failed_count
            if fetched.error is not None or persistence_error is not None:
                failures += max(
                    1 if fetched.error is not None else 0,
                    1 if persistence_error is not None else 0,
                )

        result = IngestionResult(checked, discovered, created, duplicates, failures)
        logger.info(
            "Ingestion run completed sources_checked=%d discovered=%d created=%d "
            "duplicates=%d failures=%d duration_ms=%d",
            result.sources_checked,
            result.discovered,
            result.created,
            result.duplicates,
            result.failures,
            max(0, int((time.monotonic() - run_started) * 1000)),
        )
        return result

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
