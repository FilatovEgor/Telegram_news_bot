import asyncio
import logging

import httpx

from app.sources.base import SourceArticle
from app.sources.mrc.parser import parse_article_html, parse_listing_html

logger = logging.getLogger(__name__)


class MRCSource:
    key = "mrc"
    name = "MRC"

    def __init__(self, client: httpx.AsyncClient, listing_url: str, concurrency: int = 5) -> None:
        self._client = client
        self._listing_url = listing_url
        self._semaphore = asyncio.Semaphore(concurrency)

    async def _fetch_article(self, url: str) -> SourceArticle:
        async with self._semaphore:
            response = await self._client.get(url)
            response.raise_for_status()
            return parse_article_html(response.text, str(response.url))

    async def fetch_latest(self, limit: int = 50) -> list[SourceArticle]:
        response = await self._client.get(self._listing_url)
        response.raise_for_status()
        urls = parse_listing_html(response.text, base_url=str(response.url), limit=limit)
        results = await asyncio.gather(*(self._fetch_article(url) for url in urls), return_exceptions=True)
        articles: list[SourceArticle] = []
        for url, result in zip(urls, results, strict=True):
            if isinstance(result, Exception):
                logger.warning("Could not parse MRC article %s: %s", url, result)
                continue
            articles.append(result)
        return articles
