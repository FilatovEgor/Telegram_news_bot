"""Configurable FSM storage: in-memory for the legacy single-instance mode, Redis for replicas."""

from aiogram.fsm.storage.base import BaseStorage, DefaultKeyBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

from app.config import Settings


def build_fsm_storage(settings: Settings) -> tuple[BaseStorage, Redis | None]:
    """Build the configured FSM backend and return its Redis client when enabled."""
    if settings.fsm_storage == "memory":
        return MemoryStorage(), None

    redis_url = settings.redis_url_value
    if redis_url is None:
        raise ValueError("REDIS_URL is required when FSM_STORAGE=redis")

    redis_client = Redis.from_url(redis_url, decode_responses=False)
    storage = RedisStorage(
        redis=redis_client,
        key_builder=DefaultKeyBuilder(prefix=settings.fsm_key_prefix, with_bot_id=True),
        state_ttl=settings.fsm_state_ttl_seconds,
        data_ttl=settings.fsm_data_ttl_seconds,
    )
    return storage, redis_client
