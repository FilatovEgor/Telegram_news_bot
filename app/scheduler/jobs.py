from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.services.ingestion import IngestionService


def build_scheduler(
    ingestion_service: IngestionService,
    timezone: str = "UTC",
    interval_minutes: int = 60,
    source_limit: int = 50,
) -> AsyncIOScheduler:
    """Schedule ingestion immediately and then at the configured interval."""
    scheduler = AsyncIOScheduler(timezone=timezone)
    scheduler.add_job(
        ingestion_service.ingest,
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
