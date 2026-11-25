from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(slots=True, frozen=True)
class SourceArticle:
    source_key: str
    external_id: str
    url: str
    title: str
    content: str
    tags: list[str] = field(default_factory=list)
    published_at: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class SourceFetchResult:
    articles: list[SourceArticle] = field(default_factory=list)
    attempted_count: int = 0
    failed_count: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def fetched_count(self) -> int:
        return len(self.articles)


class NewsSource(Protocol):
    key: str
    name: str
    kind: str
    base_url: str

    async def fetch_latest(self, limit: int = 50) -> SourceFetchResult: ...
