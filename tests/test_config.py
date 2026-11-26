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
