import logging
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.repositories.articles import get_or_create_source, save_discovered_article
from app.sources.base import NewsSource

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class IngestionResult:
    sources_checked: int
    discovered: int
    created: int


class IngestionService:
    def __init__(self, sources: list[NewsSource], session_factory: async_sessionmaker) -> None:
        self._sources = sources
        self._session_factory = session_factory

    async def ingest(self, limit: int = 50) -> IngestionResult:
        checked = discovered = created = 0
        for adapter in self._sources:
            checked += 1
            try:
                items = await adapter.fetch_latest(limit=limit)
            except Exception:
                logger.exception("News source fetch failed: %s", adapter.key)
                continue
            discovered += len(items)
            if not items:
                continue
            parsed = urlsplit(items[0].url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            async with self._session_factory() as session, session.begin():
                source = await get_or_create_source(session, adapter.key, adapter.name, "mrc" if adapter.key == "mrc" else "rss", base_url)
                for item in items:
                    created += int(await save_discovered_article(session, source, item))
        return IngestionResult(checked, discovered, created)
