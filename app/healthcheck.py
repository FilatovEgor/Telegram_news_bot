"""Container readiness probe for PostgreSQL and the Telegram Bot API."""

import asyncio
import logging

from aiogram import Bot

from app.config import get_settings
from app.database.session import build_session_factory
from app.logging_config import configure_logging
from app.readiness import check_readiness

logger = logging.getLogger(__name__)


async def run_healthcheck() -> None:
    settings = get_settings()
    settings.validate_runtime()
    engine, _ = build_session_factory(settings)
    assert settings.bot_token is not None
    bot = Bot(token=settings.bot_token.get_secret_value())
    try:
        await check_readiness(engine, bot)
    finally:
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
