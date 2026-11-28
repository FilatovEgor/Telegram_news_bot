import asyncio
import logging

import httpx
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.ai.agent import EditorialAgent
from app.ai.concurrency import AIConcurrencyLimiter
from app.ai.openai_provider import OpenAIProvider
from app.bot.routers import commands_router, editorial_router, sources_router, workflow_router
from app.config import Settings, get_settings
from app.database.advisory_lock import (
    PostgresAdvisoryLock,
    build_advisory_lock_engine,
)
from app.database.observability import install_pool_observability, install_slow_query_logging
from app.database.session import build_session_factory
from app.fsm import build_fsm_storage
from app.logging_config import configure_logging
from app.readiness import check_readiness
from app.scheduler.jobs import build_scheduler
from app.services.editorial import EditorialService
from app.services.ingestion import IngestionService
from app.services.publishing import PublicationService
from app.services.translation import TranslationService
from app.sources.registry import build_sources
from app.webhook import serve_webhook

logger = logging.getLogger(__name__)


def build_editorial_agent(settings: Settings, provider: OpenAIProvider) -> EditorialAgent:
    return EditorialAgent(
        provider,
        max_tool_rounds=settings.ai_max_tool_rounds,
        retry_attempts=settings.ai_retry_attempts,
        retry_base_delay_seconds=settings.ai_retry_base_delay_seconds,
        request_timeout_seconds=settings.ai_request_timeout_seconds,
        run_timeout_seconds=settings.ai_run_timeout_seconds,
        max_input_chars=settings.ai_max_input_chars,
        max_completion_tokens_per_request=settings.ai_max_completion_tokens_per_request,
        max_completion_tokens_per_article=settings.ai_max_completion_tokens_per_article,
        max_summary_words=settings.ai_summary_max_words,
        concurrency_limiter=AIConcurrencyLimiter(
            max_concurrent_requests=settings.ai_max_concurrent_requests,
            max_editorial_concurrency=settings.ai_max_editorial_concurrency,
            max_translation_concurrency=settings.ai_max_translation_concurrency,
        ),
    )


async def run_application(settings: Settings) -> None:
    settings.validate_runtime()
    engine, session_factory = build_session_factory(settings)
    lock_engine = build_advisory_lock_engine(settings)
    install_slow_query_logging(engine, settings.db_slow_query_threshold_ms)
    install_pool_observability(engine, max_overflow=settings.db_max_overflow)
    http_client = None
    ai_provider = OpenAIProvider(settings) if settings.ai_provider == "openai" else None
    scheduler = None
    assert settings.bot_token is not None
    bot = Bot(token=settings.bot_token.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    fsm_storage, redis_client = build_fsm_storage(settings)
    dispatcher = Dispatcher(storage=fsm_storage)
    dispatcher.include_router(commands_router)
    dispatcher.include_router(sources_router)
    dispatcher.include_router(editorial_router)
    dispatcher.include_router(workflow_router)
    dispatcher["settings"] = settings
    dispatcher["publication_service"] = PublicationService(session_factory)
    try:
        await check_readiness(engine, bot, redis_client)
        logger.info("Required dependencies are ready")
        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.http_timeout_seconds),
            limits=httpx.Limits(max_connections=settings.http_max_connections),
            headers={"User-Agent": "TelegramNewsBot/2.0"},
        )
        sources = build_sources(settings, http_client)
        if not sources:
            raise ValueError("No news sources configured; enable MRC or configure RSS_FEEDS")
        ingestion_service = IngestionService(
            sources,
            session_factory,
            settings=settings,
            distributed_lock=PostgresAdvisoryLock(lock_engine),
        )
        dispatcher["ingestion_service"] = ingestion_service
        if ai_provider is not None:
            agent = build_editorial_agent(settings, ai_provider)
            dispatcher["editorial_agent"] = agent
            dispatcher["editorial_service"] = EditorialService(agent, session_factory, settings)
            dispatcher["translation_service"] = TranslationService(agent, session_factory, settings)
        else:
            dispatcher["editorial_agent"] = None
            dispatcher["editorial_service"] = None
            dispatcher["translation_service"] = None

        # The first ingestion is scheduled immediately, but never awaited by bot startup.
        scheduler = build_scheduler(
            ingestion_service,
            timezone=settings.timezone,
            interval_minutes=settings.ingestion_interval_minutes,
            source_limit=settings.source_fetch_limit,
        )
        scheduler.start()
        logger.info(
            "Starting Telegram News Bot 2.0 with %d source(s) using %s transport",
            len(sources),
            settings.bot_transport,
        )
        if settings.bot_transport == "webhook":
            await serve_webhook(dispatcher, bot, settings)
        else:
            await bot.delete_webhook(drop_pending_updates=settings.drop_pending_updates)
            await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        if scheduler is not None and scheduler.running:
            scheduler.shutdown(wait=False)
        if ai_provider is not None:
            await ai_provider.close()
        if http_client is not None:
            await http_client.aclose()
        await fsm_storage.close()
        await bot.session.close()
        await lock_engine.dispose()
        await engine.dispose()


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    await run_application(settings)


if __name__ == "__main__":
    asyncio.run(main())
