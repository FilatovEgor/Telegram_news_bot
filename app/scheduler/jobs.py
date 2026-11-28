import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.database.advisory_lock import AdvisoryLockUnavailableError
from app.services.ingestion import IngestionService

logger = logging.getLogger(__name__)


def build_scheduler(
    ingestion_service: IngestionService,
    timezone: str = "UTC",
    interval_minutes: int = 60,
    source_limit: int = 50,
) -> AsyncIOScheduler:
    """Schedule ingestion immediately and then at the configured interval."""
    scheduler = AsyncIOScheduler(timezone=timezone)
    async def run_ingestion() -> None:
        try:
            await ingestion_service.ingest(limit=source_limit)
        except AdvisoryLockUnavailableError:
            logger.info("Skipping scheduled ingestion; another instance owns the advisory lock")

    scheduler.add_job(
        run_ingestion,
        kwargs={"limit": source_limit},
        trigger="interval",
        minutes=interval_minutes,
        id="news-ingestion",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(UTC),
    )
    return scheduler
