"""Core dependency readiness checks shared by startup and container healthcheck."""

from aiogram import Bot
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def check_readiness(engine: AsyncEngine, bot: Bot) -> None:
    """Raise when PostgreSQL or the Telegram Bot API is not reachable."""
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    await bot.get_me()
