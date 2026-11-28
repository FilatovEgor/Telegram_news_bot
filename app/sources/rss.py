import asyncio
import hashlib
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

import feedparser
import httpx
from bs4 import BeautifulSoup

from app.sources.base import SourceArticle, SourceFetchResult
from app.sources.http import RateLimiter, get_with_retry
from app.sources.urls import canonicalize_url


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


def _entry_fields(entry: object) -> tuple[str, str, str, datetime | None, str]:
    raw_url = str(getattr(entry, "link", "")).strip()
    title = str(getattr(entry, "title", "")).strip()
    external_id = str(getattr(entry, "id", "")).strip()
    return raw_url, title, external_id, _entry_date(entry), _entry_content(entry)


class RSSSource:
    kind = "rss"

    def __init__(
        self,
        client: httpx.AsyncClient,
        feed_url: str,
        *,
        rate_limiter: RateLimiter | None = None,
        retry_attempts: int = 3,
        retry_base_delay_seconds: float = 0.25,
        retry_max_delay_seconds: float = 4.0,
    ) -> None:
        self._client = client
        self.feed_url = feed_url
        parsed_url = urlsplit(feed_url)
        host = parsed_url.netloc.lower() or "feed"
        digest = hashlib.sha256(feed_url.encode("utf-8")).hexdigest()[:12]
        self.key = f"rss-{digest}"
        self.name = f"RSS: {host}"
        self.base_url = f"{parsed_url.scheme}://{parsed_url.netloc}" if parsed_url.scheme and parsed_url.netloc else ""
        self._rate_limiter = rate_limiter
        self._retry_attempts = retry_attempts
        self._retry_base_delay_seconds = retry_base_delay_seconds
        self._retry_max_delay_seconds = retry_max_delay_seconds

    async def fetch_latest(self, limit: int = 50) -> SourceFetchResult:
        response = await get_with_retry(
            self._client,
            self.feed_url,
            attempts=self._retry_attempts,
            base_delay_seconds=self._retry_base_delay_seconds,
            max_delay_seconds=self._retry_max_delay_seconds,
            rate_limiter=self._rate_limiter,
        )
        parsed = await asyncio.to_thread(feedparser.parse, response.content)
        entries = parsed.entries[:limit]
        articles: list[SourceArticle] = []
        warnings: list[str] = []
        failed_count = 0
        # HTML extraction is CPU work; keep it off the event loop for all entries.
        entry_fields = await asyncio.gather(
            *(asyncio.to_thread(_entry_fields, entry) for entry in entries)
        )
        for raw_url, title, external_id, published_at, content in entry_fields:
            canonical_url = canonicalize_url(urljoin(self.feed_url, raw_url)) if raw_url else None
            if not canonical_url or not title:
                failed_count += 1
                continue
            articles.append(
                SourceArticle(
                    source_key=self.key,
                    external_id=external_id or canonical_url,
                    url=canonical_url,
                    title=title,
                    content=content,
                    published_at=published_at,
                    metadata={"feed_host": urlsplit(self.feed_url).netloc.lower()},
                )
            )
        if getattr(parsed, "bozo", False):
            warnings.append("Feed parser reported malformed feed data")
        if failed_count:
            warnings.append(f"{failed_count} RSS entr(y/ies) had no valid title or HTTP(S) link")
        return SourceFetchResult(
            articles=articles,
            attempted_count=len(entries),
            failed_count=failed_count,
            warnings=warnings,
        )
