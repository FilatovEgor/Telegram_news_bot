import asyncio
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol

import httpx


class RateLimiter:
    """A small async spacing limiter shared by all configured source adapters."""

    def __init__(self, interval_seconds: float = 0.0) -> None:
        self._interval = max(0.0, interval_seconds)
        self._next_request_at = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait_seconds = max(0.0, self._next_request_at - now)
            self._next_request_at = max(now, self._next_request_at) + self._interval
        if wait_seconds:
            await asyncio.sleep(wait_seconds)


class _HTTPClient(Protocol):
    async def get(self, url: str) -> httpx.Response: ...


def _retry_after_seconds(response: httpx.Response, maximum: float) -> float | None:
    raw_value = response.headers.get("Retry-After")
    if not raw_value:
        return None
    try:
        seconds = float(raw_value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(raw_value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            seconds = (retry_at - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return None
    return min(maximum, max(0.0, seconds))


async def get_with_retry(
    client: _HTTPClient,
    url: str,
    *,
    attempts: int = 3,
    base_delay_seconds: float = 0.25,
    max_delay_seconds: float = 4.0,
    rate_limiter: RateLimiter | None = None,
) -> httpx.Response:
    """GET with bounded retries for transient transport errors, 429 and 5xx only."""
    if attempts < 1:
        raise ValueError("attempts must be at least one")

    for attempt in range(attempts):
        if rate_limiter is not None:
            await rate_limiter.acquire()
        try:
            response = await client.get(url)
        except httpx.TransportError:
            if attempt + 1 >= attempts:
                raise
            delay = min(max_delay_seconds, base_delay_seconds * (2**attempt))
            await asyncio.sleep(max(0.0, delay))
            continue

        retryable = response.status_code == 429 or 500 <= response.status_code <= 599
        if not retryable:
            response.raise_for_status()
            return response
        if attempt + 1 >= attempts:
            response.raise_for_status()

        retry_after = _retry_after_seconds(response, max_delay_seconds)
        delay = retry_after
        if delay is None:
            delay = min(max_delay_seconds, base_delay_seconds * (2**attempt))
        await asyncio.sleep(max(0.0, delay))

    raise RuntimeError("HTTP retry loop exited unexpectedly")
