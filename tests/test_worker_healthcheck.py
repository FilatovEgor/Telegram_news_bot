import pytest
from app import worker_healthcheck
from app.config import Settings


class FakeConnection:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(self, statement):
        assert str(statement) == "SELECT 1"


class FakeEngine:
    def __init__(self):
        self.disposed = False

    def connect(self):
        return FakeConnection()

    async def dispose(self):
        self.disposed = True


@pytest.mark.asyncio
async def test_worker_healthcheck_requires_only_database(monkeypatch):
    settings = Settings(database_url="postgresql+asyncpg://user:pass@localhost/news")
    engine = FakeEngine()
    monkeypatch.setattr(worker_healthcheck, "get_settings", lambda: settings)
    monkeypatch.setattr(
        worker_healthcheck,
        "build_session_factory",
        lambda current_settings: (engine, None),
    )

    await worker_healthcheck.run_healthcheck()

    assert engine.disposed
