"""Readiness probe for the dedicated ingestion worker."""

import asyncio
import logging

from sqlalchemy import text

from app.config import get_settings
from app.database.session import build_session_factory
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


async def run_healthcheck() -> None:
    settings = get_settings()
    engine, _ = build_session_factory(settings)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    finally:
        await engine.dispose()


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        asyncio.run(run_healthcheck())
    except Exception:
        logger.exception("Worker database healthcheck failed")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
