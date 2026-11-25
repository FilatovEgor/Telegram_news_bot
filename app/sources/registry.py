import httpx

from app.config import Settings
from app.sources.base import NewsSource
from app.sources.mrc.client import MRCSource
from app.sources.rss import RSSSource


def build_sources(settings: Settings, client: httpx.AsyncClient) -> list[NewsSource]:
    sources: list[NewsSource] = []
    if settings.mrc_enabled:
        sources.append(MRCSource(client, settings.mrc_listing_url))
    sources.extend(RSSSource(client, feed_url) for feed_url in settings.rss_feed_urls)
    return sources
