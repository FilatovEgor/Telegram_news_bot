from datetime import UTC, datetime

import pytest

from app.readiness import check_readiness
from app.scheduler.jobs import build_scheduler


class FakeConnection:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(self, statement):
        assert str(statement) == "SELECT 1"


class FakeEngine:
    def connect(self):
        return FakeConnection()


class FakeRedis:
    def __init__(self, error=None):
        self.error = error
        self.checked = False

    async def ping(self):
        self.checked = True
        if self.error:
            raise self.error


class FakeBot:
    def __init__(self, error=None):
        self.error = error
        self.checked = False

    async def get_me(self):
        self.checked = True
        if self.error:
            raise self.error


@pytest.mark.asyncio
async def test_readiness_checks_database_and_telegram():
    bot = FakeBot()

    await check_readiness(FakeEngine(), bot)

    assert bot.checked


@pytest.mark.asyncio
async def test_readiness_fails_when_telegram_is_unavailable():
    bot = FakeBot(RuntimeError("Telegram unavailable"))

    with pytest.raises(RuntimeError, match="Telegram unavailable"):
        await check_readiness(FakeEngine(), bot)


@pytest.mark.asyncio
async def test_ingestion_is_scheduled_immediately_without_startup_wait():
    class FakeIngestionService:
        async def ingest(self, limit):
            return limit

    scheduler = build_scheduler(FakeIngestionService(), interval_minutes=60, source_limit=17)
    scheduler.start(paused=True)
    try:
        job = scheduler.get_job("news-ingestion")
        assert job is not None
        assert job.kwargs == {"limit": 17}
        assert job.max_instances == 1
        assert job.next_run_time is not None
        assert job.next_run_time <= datetime.now(UTC)
    finally:
        scheduler.shutdown(wait=False)


@pytest.mark.asyncio
async def test_readiness_checks_redis_when_configured():
    redis_client = FakeRedis()
    bot = FakeBot()

    await check_readiness(FakeEngine(), bot, redis_client)

    assert redis_client.checked
    assert bot.checked


@pytest.mark.asyncio
async def test_readiness_fails_when_redis_is_unavailable():
    redis_client = FakeRedis(RuntimeError("Redis unavailable"))

    with pytest.raises(RuntimeError, match="Redis unavailable"):
        await check_readiness(FakeEngine(), FakeBot(), redis_client)
