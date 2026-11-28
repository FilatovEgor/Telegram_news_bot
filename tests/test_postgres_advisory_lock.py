import pytest

from sqlalchemy.pool import NullPool

from app.config import Settings
from app.database import advisory_lock
from app.database.advisory_lock import (
    AdvisoryLockUnavailableError,
    PostgresAdvisoryLock,
)


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class FakeConnection:
    def __init__(self, acquired=True, fail_unlock=False):
        self.acquired = acquired
        self.fail_unlock = fail_unlock
        self.statements = []
        self.commits = 0
        self.invalidated = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(self, statement, params):
        sql = str(statement)
        self.statements.append((sql, params))
        if "pg_try_advisory_lock" in sql:
            return FakeResult(self.acquired)
        if "pg_advisory_unlock" in sql:
            if self.fail_unlock:
                raise RuntimeError("unlock failed")
            return FakeResult(True)
        raise AssertionError(f"Unexpected SQL: {sql}")

    async def commit(self):
        self.commits += 1

    async def invalidate(self):
        self.invalidated = True


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection

    def connect(self):
        return self.connection


@pytest.mark.asyncio
async def test_advisory_lock_runs_operation_and_releases_session_lock():
    connection = FakeConnection()
    lock = PostgresAdvisoryLock(FakeEngine(connection), lock_key=1234)
    called = False

    async def operation():
        nonlocal called
        called = True
        return "completed"

    result = await lock.run(operation)

    assert result == "completed"
    assert called
    assert len(connection.statements) == 2
    assert "pg_try_advisory_lock" in connection.statements[0][0]
    assert "pg_advisory_unlock" in connection.statements[1][0]
    assert connection.statements[0][1] == {"lock_key": 1234}
    assert connection.commits == 2
    assert not connection.invalidated


@pytest.mark.asyncio
async def test_advisory_lock_skips_operation_when_another_instance_owns_it():
    connection = FakeConnection(acquired=False)
    lock = PostgresAdvisoryLock(FakeEngine(connection))
    called = False

    async def operation():
        nonlocal called
        called = True

    with pytest.raises(AdvisoryLockUnavailableError):
        await lock.run(operation)

    assert not called
    assert len(connection.statements) == 1
    assert connection.commits == 1


@pytest.mark.asyncio
async def test_advisory_lock_releases_lock_when_operation_fails():
    connection = FakeConnection()
    lock = PostgresAdvisoryLock(FakeEngine(connection))

    async def operation():
        raise RuntimeError("job failed")

    with pytest.raises(RuntimeError, match="job failed"):
        await lock.run(operation)

    assert "pg_advisory_unlock" in connection.statements[-1][0]
    assert connection.commits == 2


@pytest.mark.asyncio
async def test_advisory_lock_invalidates_connection_if_unlock_fails(caplog):
    connection = FakeConnection(fail_unlock=True)
    lock = PostgresAdvisoryLock(FakeEngine(connection))

    async def operation():
        return "completed"

    assert await lock.run(operation) == "completed"
    assert connection.invalidated
    assert "invalidating its connection" in caplog.text


def test_advisory_lock_engine_uses_null_pool(monkeypatch):
    captured = {}
    engine = object()

    def fake_create_async_engine(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return engine

    monkeypatch.setattr(advisory_lock, "create_async_engine", fake_create_async_engine)
    settings = Settings(database_url="postgresql+asyncpg://user:pass@localhost/news")

    result = advisory_lock.build_advisory_lock_engine(settings)

    assert result is engine
    assert captured == {
        "url": settings.database_url_value,
        "poolclass": NullPool,
        "pool_pre_ping": True,
    }
