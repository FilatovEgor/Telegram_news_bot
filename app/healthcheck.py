"""Container readiness probe for PostgreSQL and the Telegram Bot API."""

import asyncio
import logging

import httpx
from aiogram import Bot

from app.config import get_settings
from app.database.session import build_session_factory
from app.fsm import build_fsm_storage
from app.logging_config import configure_logging
from app.readiness import check_readiness

logger = logging.getLogger(__name__)


async def run_healthcheck() -> None:
    settings = get_settings()
    settings.validate_runtime()
    engine, _ = build_session_factory(settings)
    assert settings.bot_token is not None
    bot = Bot(token=settings.bot_token.get_secret_value())
    fsm_storage, redis_client = build_fsm_storage(settings)
    try:
        await check_readiness(engine, bot, redis_client)
        if settings.bot_transport == "webhook":
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(
                    f"http://127.0.0.1:{settings.webhook_port}/healthz"
                )
                response.raise_for_status()
    finally:
        await fsm_storage.close()
        await bot.session.close()
        await engine.dispose()


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        asyncio.run(run_healthcheck())
    except Exception:
        logger.exception("Container readiness check failed")
        raise SystemExit(1) from None
    logger.debug("Container readiness check passed")


if __name__ == "__main__":
    main()
