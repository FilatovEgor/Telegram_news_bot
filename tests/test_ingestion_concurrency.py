import asyncio

import pytest

from app.config import Settings
from app.services.ingestion import IngestionService


class FakeSource:
    kind = "rss"
    base_url = ""

    def __init__(self, key, fetch):
        self.key = key
        self.name = key
        self._fetch = fetch

    async def fetch_latest(self, limit=50):
        return await self._fetch(limit)


@pytest.mark.asyncio
async def test_source_fetches_respect_configured_concurrency_and_keep_order():
    active = 0
    peak_active = 0
    started = []

    async def fetch(name):
        async def run(_limit):
            nonlocal active, peak_active
            active += 1
            peak_active = max(peak_active, active)
            started.append(name)
            await asyncio.sleep(0.02)
            active -= 1
            return []
        return run

    sources = [
        FakeSource(name, await fetch(name))
        for name in ("one", "two", "three", "four", "five")
    ]
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        source_fetch_concurrency=2,
    )
    service = IngestionService(sources, session_factory=None, settings=settings)

    results = await service._fetch_sources(limit=17)

    assert peak_active == 2
    assert started == ["one", "two", "three", "four", "five"]
    assert len(results) == 5
    assert all(result.error is None for result in results)


@pytest.mark.asyncio
async def test_source_fetch_failure_isolated_and_does_not_cancel_other_sources():
    completed = []

    async def successful(_limit):
        await asyncio.sleep(0)
        completed.append("success")
        return []

    async def failing(_limit):
        await asyncio.sleep(0)
        raise TimeoutError("upstream timed out")

    sources = [
        FakeSource("failed", failing),
        FakeSource("successful", successful),
    ]
    service = IngestionService(
        sources,
        session_factory=None,
        settings=Settings(
            database_url="postgresql+asyncpg://user:pass@localhost/news",
            source_fetch_concurrency=2,
        ),
    )

    results = await service._fetch_sources(limit=10)

    assert isinstance(results[0].error, TimeoutError)
    assert results[1].error is None
    assert completed == ["success"]
    assert results[0].result.articles == []
    assert results[1].result.articles == []


def test_source_fetch_concurrency_defaults_and_validation():
    settings = Settings(database_url="postgresql+asyncpg://user:pass@localhost/news")
    assert settings.source_fetch_concurrency == 4

    with pytest.raises(Exception):
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost/news",
            source_fetch_concurrency=0,
        )
