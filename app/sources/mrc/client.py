import asyncio

import httpx

from app.sources.base import SourceArticle, SourceFetchResult
from app.sources.http import RateLimiter, get_with_retry
from app.sources.mrc.parser import MRC_BASE_URL, parse_article_html, parse_listing_html


class MRCSource:
    key = "mrc"
    kind = "mrc"
    name = "MRC"
    base_url = MRC_BASE_URL

    def __init__(
        self,
        client: httpx.AsyncClient,
        listing_url: str,
        concurrency: int = 5,
        *,
        rate_limiter: RateLimiter | None = None,
        retry_attempts: int = 3,
        retry_base_delay_seconds: float = 0.25,
        retry_max_delay_seconds: float = 4.0,
    ) -> None:
        self._client = client
        self._listing_url = listing_url
        self._semaphore = asyncio.Semaphore(concurrency)
        self._rate_limiter = rate_limiter
        self._retry_attempts = retry_attempts
        self._retry_base_delay_seconds = retry_base_delay_seconds
        self._retry_max_delay_seconds = retry_max_delay_seconds

    async def _get(self, url: str) -> httpx.Response:
        return await get_with_retry(
            self._client,
            url,
            attempts=self._retry_attempts,
            base_delay_seconds=self._retry_base_delay_seconds,
            max_delay_seconds=self._retry_max_delay_seconds,
            rate_limiter=self._rate_limiter,
        )

    async def _fetch_article(self, url: str) -> SourceArticle:
        async with self._semaphore:
            response = await self._get(url)
            return parse_article_html(response.text, str(response.url))

    async def fetch_latest(self, limit: int = 50) -> SourceFetchResult:
        response = await self._get(self._listing_url)
        urls = parse_listing_html(response.text, base_url=str(response.url), limit=limit)
        results = await asyncio.gather(
            *(self._fetch_article(url) for url in urls),
            return_exceptions=True,
        )
        articles: list[SourceArticle] = []
        warnings: list[str] = []
        failed_count = 0
        for result in results:
            if isinstance(result, Exception):
                failed_count += 1
                warnings.append(f"An MRC article could not be fetched or parsed ({type(result).__name__})")
                continue
            articles.append(result)
        return SourceFetchResult(
            articles=articles,
            attempted_count=len(urls),
            failed_count=failed_count,
            warnings=warnings,
        )
