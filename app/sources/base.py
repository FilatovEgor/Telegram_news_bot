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


class NewsSource(Protocol):
    key: str
    name: str

    async def fetch_latest(self, limit: int = 50) -> list[SourceArticle]: ...
