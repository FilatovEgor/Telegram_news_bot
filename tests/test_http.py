import asyncio

import httpx
import pytest

from app.sources.http import get_with_retry


class FakeHTTPClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def get(self, url: str) -> httpx.Response:
        self.calls += 1
        return self.responses.pop(0)


def response(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    request = httpx.Request("GET", "https://example.com/feed.xml")
    return httpx.Response(status, headers=headers, request=request)


@pytest.fixture
def no_sleep(monkeypatch):
    async def sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", sleep)


@pytest.mark.asyncio
async def test_get_retries_server_error_then_returns_success(no_sleep):
    client = FakeHTTPClient([response(503), response(200)])
    result = await get_with_retry(client, "https://example.com/feed.xml", attempts=2)
    assert result.status_code == 200
    assert client.calls == 2


@pytest.mark.asyncio
async def test_get_does_not_retry_non_retryable_4xx(no_sleep):
    client = FakeHTTPClient([response(404), response(200)])
    with pytest.raises(httpx.HTTPStatusError):
        await get_with_retry(client, "https://example.com/feed.xml", attempts=3)
    assert client.calls == 1


@pytest.mark.asyncio
async def test_get_honors_bounded_retry_after_header(monkeypatch):
    waits: list[float] = []

    async def capture_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", capture_sleep)
    client = FakeHTTPClient([response(429, {"Retry-After": "60"}), response(200)])
    await get_with_retry(
        client,
        "https://example.com/feed.xml",
        attempts=2,
        max_delay_seconds=2,
    )
    assert waits == [2]
    assert client.calls == 2
