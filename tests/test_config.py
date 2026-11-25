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
