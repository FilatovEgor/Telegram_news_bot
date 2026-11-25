import asyncio
import logging

import httpx
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.agent import EditorialAgent
from app.ai.openai_provider import OpenAIProvider
from app.bot.routers import commands_router
from app.config import Settings, get_settings
from app.logging_config import configure_logging
from app.scheduler.jobs import build_scheduler
from app.services.ingestion import IngestionService
from app.sources.registry import build_sources

logger = logging.getLogger(__name__)


async def run_application(settings: Settings) -> None:
    settings.validate_runtime()
    engine = create_async_engine(settings.database_url_value, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    http_client = None
    ai_provider = OpenAIProvider(settings) if settings.ai_provider == "openai" else None
    scheduler = None
    assert settings.bot_token is not None
    bot = Bot(token=settings.bot_token.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher()
    dispatcher.include_router(commands_router)
    dispatcher["settings"] = settings
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        logger.info("PostgreSQL connection established")
        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.http_timeout_seconds),
            limits=httpx.Limits(max_connections=settings.http_max_connections),
            headers={"User-Agent": "TelegramNewsBot/2.0"},
        )
        sources = build_sources(settings, http_client)
        if not sources:
            raise ValueError("No news sources configured; enable MRC or configure RSS_FEEDS")
        ingestion_service = IngestionService(sources, session_factory)
        dispatcher["ingestion_service"] = ingestion_service
        dispatcher["editorial_agent"] = EditorialAgent(ai_provider) if ai_provider is not None else None
        await ingestion_service.ingest(limit=settings.source_fetch_limit)
        scheduler = build_scheduler(ingestion_service, timezone=settings.timezone, interval_minutes=settings.ingestion_interval_minutes, source_limit=settings.source_fetch_limit)
        scheduler.start()
        await bot.delete_webhook(drop_pending_updates=settings.drop_pending_updates)
        logger.info("Starting Telegram News Bot 2.0 with %d source(s)", len(sources))
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        if scheduler is not None and scheduler.running:
            scheduler.shutdown(wait=False)
        if ai_provider is not None:
            await ai_provider.close()
        if http_client is not None:
            await http_client.aclose()
        await bot.session.close()
        await engine.dispose()


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    await run_application(settings)


if __name__ == "__main__":
    asyncio.run(main())
