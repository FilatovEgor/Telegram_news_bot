import pytest
from pydantic import ValidationError

from app.config import Settings


def test_rss_feed_urls_are_split_and_trimmed():
    settings = Settings(
        bot_token="test-token",
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        openai_api_key="test-key",
        rss_feeds=" https://example.com/a.xml,https://example.org/b.xml ,",
    )
    assert settings.rss_feed_urls == [
        "https://example.com/a.xml",
        "https://example.org/b.xml",
    ]
    assert settings.openai_model == "gpt-6-luna"


def test_duplicate_threshold_must_be_between_zero_and_one():
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost/news",
            duplicate_title_similarity_threshold=1.1,
        )


def test_retry_and_concurrency_settings_must_be_positive():
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost/news",
            source_retry_attempts=0,
        )


def test_ai_run_limits_have_safe_defaults():
    settings = Settings(database_url="postgresql+asyncpg://user:pass@localhost/news")
    assert settings.ai_max_tool_rounds == 3
    assert settings.ai_retry_attempts == 2
    assert settings.ai_max_completion_tokens_per_article == 1800


def test_ai_tool_rounds_are_bounded():
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost/news",
            ai_max_tool_rounds=9,
        )



def test_publish_channels_are_selected_by_language():
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        publish_channel_id="@news_ru",
        publish_channel_id_en="@news_en",
    )
    assert settings.publish_channel_for("ru") == "@news_ru"
    assert settings.publish_channel_for("en") == "@news_en"
    with pytest.raises(ValueError, match="Only ru and en"):
        settings.publish_channel_for("de")


def test_ai_concurrency_limits_have_bounded_defaults():
    settings = Settings(database_url="postgresql+asyncpg://user:pass@localhost/news")
    assert settings.ai_max_concurrent_requests == 3
    assert settings.ai_max_editorial_concurrency == 2
    assert settings.ai_max_translation_concurrency == 1


@pytest.mark.parametrize(
    "setting",
    [
        "ai_max_concurrent_requests",
        "ai_max_editorial_concurrency",
        "ai_max_translation_concurrency",
    ],
)
def test_ai_concurrency_limits_must_be_positive(setting):
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost/news",
            **{setting: 0},
        )


def test_database_observability_threshold_defaults_and_validation():
    settings = Settings(database_url="postgresql+asyncpg://user:pass@localhost/news")
    assert settings.db_slow_query_threshold_ms == 250
    assert settings.source_persist_batch_size == 100

    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost/news",
            db_slow_query_threshold_ms=0,
        )


def test_source_persist_batch_size_must_be_positive():
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost/news",
            source_persist_batch_size=0,
        )



def test_database_pool_settings_have_conservative_defaults_and_capacity():
    settings = Settings(database_url="postgresql+asyncpg://user:pass@localhost/news")

    assert settings.db_pool_size == 5
    assert settings.db_max_overflow == 5
    assert settings.db_pool_timeout_seconds == 30
    assert settings.db_pool_recycle_seconds == 1800
    assert settings.db_pool_capacity_per_instance == 10


def test_database_pool_allows_disabling_overflow():
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        db_pool_size=3,
        db_max_overflow=0,
    )
    assert settings.db_pool_capacity_per_instance == 3


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("db_pool_size", 0),
        ("db_max_overflow", -1),
        ("db_pool_timeout_seconds", 0),
        ("db_pool_recycle_seconds", 0),
    ],
)
def test_database_pool_settings_reject_invalid_values(setting, value):
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost/news",
            **{setting: value},
        )


def test_fsm_defaults_preserve_single_instance_memory_storage():
    settings = Settings(database_url="postgresql+asyncpg://user:pass@localhost/news")

    assert settings.fsm_storage == "memory"
    assert settings.redis_url is None
    assert settings.fsm_key_prefix == "tgnews:fsm"
    assert settings.fsm_state_ttl_seconds == 86400
    assert settings.fsm_data_ttl_seconds == 86400


@pytest.mark.parametrize("setting", ["fsm_state_ttl_seconds", "fsm_data_ttl_seconds"])
def test_fsm_ttls_must_be_positive(setting):
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost/news",
            **{setting: 0},
        )


def test_fsm_key_prefix_must_not_be_blank():
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost/news",
            fsm_key_prefix="   ",
        )


def test_blank_redis_url_is_treated_as_unset():
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        redis_url="   ",
    )

    assert settings.redis_url is None
