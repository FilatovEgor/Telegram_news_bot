from app.config import Settings
from app.database import session as database_session


def test_build_session_factory_applies_pool_limits(monkeypatch):
    captured = {}
    engine = object()

    def fake_create_async_engine(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return engine

    def fake_sessionmaker(bound_engine, **kwargs):
        assert bound_engine is engine
        assert kwargs == {"expire_on_commit": False}
        return "session-factory"

    monkeypatch.setattr(database_session, "create_async_engine", fake_create_async_engine)
    monkeypatch.setattr(database_session, "async_sessionmaker", fake_sessionmaker)

    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        db_pool_size=4,
        db_max_overflow=2,
        db_pool_timeout_seconds=12,
        db_pool_recycle_seconds=900,
    )
    returned_engine, factory = database_session.build_session_factory(settings)

    assert returned_engine is engine
    assert factory == "session-factory"
    assert captured == {
        "url": settings.database_url_value,
        "pool_pre_ping": True,
        "pool_size": 4,
        "max_overflow": 2,
        "pool_timeout": 12,
        "pool_recycle": 900,
    }
