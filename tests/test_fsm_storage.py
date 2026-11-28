from aiogram.fsm.storage.memory import MemoryStorage

from app.config import Settings
from app.fsm import build_fsm_storage


def test_memory_fsm_remains_the_default():
    settings = Settings(database_url="postgresql+asyncpg://user:pass@localhost/news")

    storage, redis_client = build_fsm_storage(settings)

    assert isinstance(storage, MemoryStorage)
    assert redis_client is None


def test_redis_fsm_uses_shared_bot_scoped_keys_and_ttls(monkeypatch):
    captured = {}
    redis_client = object()

    def fake_from_url(url, **kwargs):
        captured["url"] = url
        captured["redis_kwargs"] = kwargs
        return redis_client

    class FakeRedisStorage:
        def __init__(self, **kwargs):
            captured["storage_kwargs"] = kwargs

    monkeypatch.setattr("app.fsm.Redis.from_url", fake_from_url)
    monkeypatch.setattr("app.fsm.RedisStorage", FakeRedisStorage)
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        fsm_storage="redis",
        redis_url="redis://localhost:6379/3",
        fsm_key_prefix="bot:test",
        fsm_state_ttl_seconds=3600,
        fsm_data_ttl_seconds=7200,
    )

    storage, returned_client = build_fsm_storage(settings)

    assert isinstance(storage, FakeRedisStorage)
    assert returned_client is redis_client
    assert captured["url"] == "redis://localhost:6379/3"
    assert captured["redis_kwargs"] == {"decode_responses": False}
    assert captured["storage_kwargs"]["redis"] is redis_client
    assert captured["storage_kwargs"]["key_builder"].prefix == "bot:test"
    assert captured["storage_kwargs"]["key_builder"].with_bot_id is True
    assert captured["storage_kwargs"]["state_ttl"] == 3600
    assert captured["storage_kwargs"]["data_ttl"] == 7200


def test_redis_fsm_requires_url_at_runtime():
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        bot_token="test-token",
        openai_api_key="test-key",
        fsm_storage="redis",
    )

    try:
        settings.validate_runtime()
    except ValueError as exc:
        assert "REDIS_URL is required" in str(exc)
    else:
        raise AssertionError("Expected missing Redis URL to fail runtime validation")
