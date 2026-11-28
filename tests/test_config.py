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


def test_polling_remains_the_default_transport():
    settings = Settings(database_url="postgresql+asyncpg://user:pass@localhost/news")

    assert settings.bot_transport == "polling"
    assert settings.webhook_url is None


def test_webhook_transport_requires_https_url_and_secret():
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        bot_token="test-token",
        openai_api_key="test-key",
        bot_transport="webhook",
        webhook_base_url="https://news.example.com/",
        webhook_secret_token="secret_token-123",
    )

    settings.validate_runtime()

    assert settings.webhook_url == "https://news.example.com/telegram/webhook"
    assert settings.webhook_secret_value == "secret_token-123"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"webhook_secret_token": "secret"}, "WEBHOOK_BASE_URL is required"),
        ({"webhook_base_url": "https://news.example.com"}, "WEBHOOK_SECRET_TOKEN is required"),
        (
            {
                "webhook_base_url": "https://news.example.com",
                "webhook_secret_token": "secret",
                "drop_pending_updates": True,
            },
            "DROP_PENDING_UPDATES must be false",
        ),
    ],
)
def test_webhook_runtime_rejects_missing_or_unsafe_settings(overrides, message):
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        bot_token="test-token",
        openai_api_key="test-key",
        bot_transport="webhook",
        **overrides,
    )

    with pytest.raises(ValueError, match=message):
        settings.validate_runtime()


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("webhook_base_url", "http://news.example.com"),
        ("webhook_base_url", "https://news.example.com/path"),
        ("webhook_base_url", "https://news.example.com:8080"),
        ("webhook_secret_token", "secret with spaces"),
        ("webhook_secret_token", "bad$token"),
        ("webhook_path", "telegram/webhook"),
        ("webhook_path", "/hook?token=bad"),
        ("webhook_port", 0),
        ("webhook_port", 65536),
    ],
)
def test_webhook_settings_reject_invalid_values(setting, value):
    with pytest.raises(ValidationError):
        Settings(
            database_url="postgresql+asyncpg://user:pass@localhost/news",
            **{setting: value},
        )


def test_ingestion_scheduler_is_enabled_by_default_for_single_instance():
    settings = Settings(database_url="postgresql+asyncpg://user:pass@localhost/news")

    assert settings.ingestion_scheduler_enabled is True


def test_webhook_certificate_path_is_optional_and_blank_is_normalized():
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        webhook_certificate_path="   ",
    )
    assert settings.webhook_certificate_path is None


def test_ip_webhook_certificate_requires_ip_url_and_existing_file(tmp_path):
    certificate = tmp_path / "telegram-webhook-public.pem"
    certificate.write_text("test certificate", encoding="utf-8")
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        bot_token="test-token",
        openai_api_key="test-key",
        bot_transport="webhook",
        webhook_base_url="https://203.0.113.10",
        webhook_secret_token="secret_token-123",
        webhook_certificate_path=str(certificate),
    )
    settings.validate_runtime()
    assert settings.webhook_certificate_path == str(certificate)


def test_ip_webhook_certificate_rejects_domain_name(tmp_path):
    certificate = tmp_path / "telegram-webhook-public.pem"
    certificate.write_text("test certificate", encoding="utf-8")
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        bot_token="test-token",
        openai_api_key="test-key",
        bot_transport="webhook",
        webhook_base_url="https://news.example.com",
        webhook_secret_token="secret_token-123",
        webhook_certificate_path=str(certificate),
    )
    with pytest.raises(ValueError, match="IP-address webhook URL"):
        settings.validate_runtime()


def test_ip_webhook_certificate_path_must_exist(tmp_path):
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        bot_token="test-token",
        openai_api_key="test-key",
        bot_transport="webhook",
        webhook_base_url="https://203.0.113.10",
        webhook_secret_token="secret_token-123",
        webhook_certificate_path=str(tmp_path / "missing.pem"),
    )
    with pytest.raises(ValueError, match="existing PEM certificate file"):
        settings.validate_runtime()


def test_webhook_secret_can_be_loaded_from_file_when_env_secret_is_unset(tmp_path):
    secret_file = tmp_path / "webhook_token"
    secret_file.write_text("a" * 64 + "\\n", encoding="utf-8")

    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        bot_transport="webhook",
        webhook_base_url="https://news.example.com",
        webhook_secret_token_file=str(secret_file),
    )

    settings.validate_runtime()
    assert settings.webhook_secret_value == "a" * 64


def test_webhook_environment_secret_takes_precedence_over_secret_file(tmp_path):
    secret_file = tmp_path / "webhook_token"
    secret_file.write_text("file-secret", encoding="utf-8")

    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        bot_transport="webhook",
        webhook_base_url="https://news.example.com",
        webhook_secret_token="environment-secret",
        webhook_secret_token_file=str(secret_file),
    )

    assert settings.webhook_secret_value == "environment-secret"


def test_missing_webhook_secret_file_fails_with_safe_error(tmp_path):
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        bot_transport="webhook",
        webhook_base_url="https://news.example.com",
        webhook_secret_token_file=str(tmp_path / "missing"),
    )

    with pytest.raises(ValueError, match="WEBHOOK_SECRET_TOKEN_FILE"):
        settings.validate_runtime()
