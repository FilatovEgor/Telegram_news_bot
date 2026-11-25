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
    assert settings.openai_model == "gpt-4"


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
