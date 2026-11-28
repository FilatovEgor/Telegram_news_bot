import httpx
import pytest

from app.sources.rss import RSSSource


class FakeHTTPClient:
    def __init__(self, content: bytes):
        self.content = content

    async def get(self, url: str) -> httpx.Response:
        request = httpx.Request("GET", url)
        return httpx.Response(200, content=self.content, request=request)


@pytest.mark.asyncio
async def test_rss_fetch_normalizes_links_and_reports_invalid_entries():
    payload = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <title>Example feed</title><link>https://example.com</link><description>Feed</description>
      <item><title>Market update</title>
        <link>https://www.example.com/news/1?utm_source=mail</link>
        <guid>market-1</guid><description><![CDATA[<p>Markets moved.</p>]]></description>
      </item>
      <item><title>Missing link</title><description>No URL</description></item>
    </channel></rss>"""
    source = RSSSource(FakeHTTPClient(payload), "https://example.com/rss.xml")
    result = await source.fetch_latest(limit=10)

    assert result.attempted_count == 2
    assert result.fetched_count == 1
    assert result.failed_count == 1
    assert result.articles[0].url == "https://example.com/news/1"
    assert result.articles[0].external_id == "market-1"
    assert result.articles[0].content == "Markets moved."


@pytest.mark.asyncio
async def test_rss_content_cleanup_uses_worker_thread(monkeypatch):
    import app.sources.rss as rss_module

    payload = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item><title>Market update</title><link>https://example.com/news/1</link>
        <description><![CDATA[<p>Markets moved.</p>]]></description>
      </item>
    </channel></rss>"""
    calls = []
    original = rss_module.asyncio.to_thread

    async def tracking_to_thread(function, *args, **kwargs):
        calls.append(function.__name__)
        return await original(function, *args, **kwargs)

    monkeypatch.setattr(rss_module.asyncio, "to_thread", tracking_to_thread)
    source = RSSSource(FakeHTTPClient(payload), "https://example.com/rss.xml")
    result = await source.fetch_latest(limit=10)

    assert result.fetched_count == 1
    assert "_entry_fields" in calls
