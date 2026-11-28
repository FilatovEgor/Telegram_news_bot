"""PostgreSQL session-level advisory locks for cross-process job coordination."""

import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

T = TypeVar("T")
INGESTION_ADVISORY_LOCK_KEY = 0x54474E455753  # Stable 64-bit key: "TGNEWS"


class AdvisoryLockUnavailableError(RuntimeError):
    """Raised when another process currently owns a distributed job lock."""


class PostgresAdvisoryLock:
    """Hold a PostgreSQL session lock on a dedicated connection while work runs."""

    def __init__(
        self,
        engine: AsyncEngine,
        lock_key: int = INGESTION_ADVISORY_LOCK_KEY,
    ) -> None:
        self._engine = engine
        self._lock_key = lock_key

    async def run(self, operation: Callable[[], Awaitable[T]]) -> T:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": self._lock_key},
            )
            acquired = bool(result.scalar_one())
            await connection.commit()
            if not acquired:
                raise AdvisoryLockUnavailableError(
                    "Another application instance is already running ingestion"
                )

            try:
                return await operation()
            finally:
                try:
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_key)"),
                        {"lock_key": self._lock_key},
                    )
                    await connection.commit()
                except Exception:
                    logger.exception(
                        "Could not release PostgreSQL advisory lock; invalidating its connection"
                    )
                    await connection.invalidate()
