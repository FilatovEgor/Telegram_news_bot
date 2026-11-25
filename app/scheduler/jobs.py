from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.services.ingestion import IngestionService


def build_scheduler(ingestion_service: IngestionService, timezone: str = "UTC", interval_minutes: int = 60, source_limit: int = 50) -> AsyncIOScheduler:
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
    )
    return scheduler
