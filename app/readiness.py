"""Core dependency readiness checks shared by startup and container healthcheck."""

from aiogram import Bot
from sqlalchemy import text
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine


async def check_readiness(
    engine: AsyncEngine,
    bot: Bot,
    redis_client: Redis | None = None,
) -> None:
    """Raise when PostgreSQL, configured Redis, or Telegram is not reachable."""
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    if redis_client is not None:
        await redis_client.ping()
    await bot.get_me()
