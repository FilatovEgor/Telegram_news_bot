import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import feedparser
import httpx
from bs4 import BeautifulSoup

from app.sources.base import SourceArticle

logger = logging.getLogger(__name__)


def _entry_date(entry: object) -> datetime | None:
    value = getattr(entry, "published", None) or getattr(entry, "updated", None)
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def _entry_content(entry: object) -> str:
    values = getattr(entry, "content", None) or []
    raw = values[0].get("value", "") if values else getattr(entry, "summary", "")
    return BeautifulSoup(str(raw), "html.parser").get_text(" ", strip=True)


class RSSSource:
    def __init__(self, client: httpx.AsyncClient, feed_url: str) -> None:
        self._client = client
        self.feed_url = feed_url
        host = urlsplit(feed_url).netloc.lower() or "feed"
        digest = hashlib.sha256(feed_url.encode("utf-8")).hexdigest()[:12]
        self.key = f"rss-{digest}"
        self.name = f"RSS: {host}"

    async def fetch_latest(self, limit: int = 50) -> list[SourceArticle]:
        response = await self._client.get(self.feed_url)
        response.raise_for_status()
        parsed = await asyncio.to_thread(feedparser.parse, response.content)
        articles: list[SourceArticle] = []
        for entry in parsed.entries[:limit]:
            url = str(getattr(entry, "link", "")).strip()
            title = str(getattr(entry, "title", "")).strip()
            if not url or not title:
                continue
            external_id = str(getattr(entry, "id", "") or url)
            articles.append(SourceArticle(
                source_key=self.key,
                external_id=external_id,
                url=url,
                title=title,
                content=_entry_content(entry),
                published_at=_entry_date(entry),
                metadata={"feed_url": self.feed_url},
            ))
        if getattr(parsed, "bozo", False):
            logger.warning("RSS feed returned a parsing warning: %s", self.feed_url)
        return articles
