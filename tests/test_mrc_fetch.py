import httpx
import pytest

from app.sources.mrc.client import MRCSource


class FakeHTTPClient:
    def __init__(self, responses):
        self.responses = list(responses)

    async def get(self, url: str) -> httpx.Response:
        status, body = self.responses.pop(0)
        request = httpx.Request("GET", url)
        return httpx.Response(status, text=body, request=request)


@pytest.mark.asyncio
async def test_mrc_fetch_reports_partial_article_failures():
    listing = (
        '<a href="/news/1-valid">valid</a>'
        '<a href="/news/2-missing">missing</a>'
    )
    article = (
        '<h1 class="h2 news-single-page-header">Market story</h1>'
        '<div class="post-content"><p>Article body</p></div>'
    )
    client = FakeHTTPClient([(200, listing), (200, article), (404, "not found")])
    source = MRCSource(client, "https://www.mrc.ru/ajax/news/")
    result = await source.fetch_latest(limit=5)

    assert result.attempted_count == 2
    assert result.fetched_count == 1
    assert result.failed_count == 1
    assert result.articles[0].title == "Market story"
