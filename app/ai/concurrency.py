import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

Workload = Literal["editorial", "translation"]


class AIConcurrencyLimiter:
    """Process-wide limits for all AI provider requests and workload-specific traffic."""

    def __init__(
        self,
        *,
        max_concurrent_requests: int = 3,
        max_editorial_concurrency: int = 2,
        max_translation_concurrency: int = 1,
    ) -> None:
        if min(
            max_concurrent_requests,
            max_editorial_concurrency,
            max_translation_concurrency,
        ) < 1:
            raise ValueError("AI concurrency limits must be positive")
        self._global = asyncio.Semaphore(max_concurrent_requests)
        self._workload = {
            "editorial": asyncio.Semaphore(max_editorial_concurrency),
            "translation": asyncio.Semaphore(max_translation_concurrency),
        }

    @asynccontextmanager
    async def slot(self, workload: Workload) -> AsyncIterator[None]:
        """Reserve a workload slot and a global provider slot for one HTTP attempt."""
        async with self._workload[workload]:
            async with self._global:
                yield
