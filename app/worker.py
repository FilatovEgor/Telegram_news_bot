"""Dedicated ingestion scheduler process, independent of Telegram update handling."""

import asyncio
import logging
import signal

import httpx
from sqlalchemy import text

from app.config import Settings, get_settings
from app.database.advisory_lock import PostgresAdvisoryLock, build_advisory_lock_engine
from app.database.observability import install_pool_observability, install_slow_query_logging
from app.database.session import build_session_factory
from app.logging_config import configure_logging
from app.scheduler.jobs import build_scheduler
from app.services.ingestion import IngestionService
from app.sources.registry import build_sources

logger = logging.getLogger(__name__)


async def run_worker(settings: Settings) -> None:
    if not settings.ingestion_scheduler_enabled:
        raise ValueError("INGESTION_SCHEDULER_ENABLED must be true for the worker process")

    engine, session_factory = build_session_factory(settings)
    lock_engine = build_advisory_lock_engine(settings)
    install_slow_query_logging(engine, settings.db_slow_query_threshold_ms)
    install_pool_observability(engine, max_overflow=settings.db_max_overflow)
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.http_timeout_seconds),
        limits=httpx.Limits(max_connections=settings.http_max_connections),
        headers={"User-Agent": "TelegramNewsBot/2.0 worker"},
    )
    scheduler = None
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    handled_signals: list[signal.Signals] = []
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        sources = build_sources(settings, http_client)
        if not sources:
            raise ValueError("No news sources configured; enable MRC or configure RSS_FEEDS")
        ingestion_service = IngestionService(
            sources,
            session_factory,
            settings=settings,
            distributed_lock=PostgresAdvisoryLock(lock_engine),
        )
        scheduler = build_scheduler(
            ingestion_service,
            timezone=settings.timezone,
            interval_minutes=settings.ingestion_interval_minutes,
            source_limit=settings.source_fetch_limit,
        )
        scheduler.start()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
                handled_signals.append(sig)
            except NotImplementedError:
                logger.warning("Signal handler unavailable for %s", sig.name)
        logger.info("Dedicated ingestion worker started with %d source(s)", len(sources))
        await stop_event.wait()
    finally:
        for sig in handled_signals:
            loop.remove_signal_handler(sig)
        if scheduler is not None and scheduler.running:
            scheduler.shutdown(wait=False)
        await http_client.aclose()
        await lock_engine.dispose()
        await engine.dispose()


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    await run_worker(settings)


if __name__ == "__main__":
    asyncio.run(main())
