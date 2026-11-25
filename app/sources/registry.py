import httpx

from app.config import Settings
from app.sources.base import NewsSource
from app.sources.http import RateLimiter
from app.sources.mrc.client import MRCSource
from app.sources.rss import RSSSource


def build_sources(settings: Settings, client: httpx.AsyncClient) -> list[NewsSource]:
    rate_limiter = RateLimiter(settings.source_request_interval_seconds)
    common = {
        "rate_limiter": rate_limiter,
        "retry_attempts": settings.source_retry_attempts,
        "retry_base_delay_seconds": settings.source_retry_base_delay_seconds,
        "retry_max_delay_seconds": settings.source_retry_max_delay_seconds,
    }
    sources: list[NewsSource] = []
    if settings.mrc_enabled:
        sources.append(
            MRCSource(
                client,
                settings.mrc_listing_url,
                concurrency=settings.mrc_article_concurrency,
                **common,
            )
        )
    sources.extend(RSSSource(client, feed_url, **common) for feed_url in settings.rss_feed_urls)
    return sources
