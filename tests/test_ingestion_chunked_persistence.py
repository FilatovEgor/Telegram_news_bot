import uuid
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.database.models import SourceRun
from app.services import ingestion as ingestion_module
from app.services.ingestion import IngestionService
from app.sources.base import SourceArticle, SourceFetchResult


class _AsyncContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class _FakeSession:
    def __init__(self):
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def begin(self):
        return _AsyncContext()

    def add(self, item):
        self.added.append(item)


class _FakeSessionFactory:
    def __init__(self):
        self.sessions = []

    def __call__(self):
        session = _FakeSession()
        self.sessions.append(session)
        return session


class _FakeSource:
    key = "chunked-source"
    name = "Chunked source"
    kind = "rss"
    base_url = None

    def __init__(self, articles):
        self._articles = articles

    async def fetch_latest(self, limit=50):
        return SourceFetchResult(
            articles=self._articles,
            attempted_count=len(self._articles),
        )


@pytest.mark.asyncio
async def test_ingestion_persists_bounded_chunks_and_aggregates_source_run(monkeypatch):
    articles = [
        SourceArticle(
            source_key="chunked-source",
            external_id=f"article-{index}",
            url=f"https://example.com/{index}",
            title=f"Article {index}",
            content=f"Body {index}",
        )
        for index in range(5)
    ]
    source_row = SimpleNamespace(
        id=uuid.uuid4(),
        consecutive_failures=0,
        last_success_at=None,
        last_status=None,
        last_attempt_at=None,
        last_duration_ms=None,
        last_fetched_count=0,
        last_error=None,
    )
    saved_chunk_sizes = []
    duplicate_chunk_sizes = []

    async def get_source(*_args, **_kwargs):
        return source_row

    async def save_chunk(_session, _source, chunk):
        saved_chunk_sizes.append(len(chunk))
        return [SimpleNamespace(id=uuid.uuid4(), source_id=source_row.id) for _ in chunk]

    async def record_duplicates(_session, chunk, **_kwargs):
        duplicate_chunk_sizes.append(len(chunk))
        return 1

    monkeypatch.setattr(ingestion_module, "get_or_create_source", get_source)
    monkeypatch.setattr(ingestion_module, "save_discovered_articles", save_chunk)
    monkeypatch.setattr(
        ingestion_module,
        "record_duplicate_candidates_for_articles",
        record_duplicates,
    )

    sessions = _FakeSessionFactory()
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        source_persist_batch_size=2,
    )
    service = IngestionService([_FakeSource(articles)], sessions, settings)

    result = await service.ingest()

    assert saved_chunk_sizes == [2, 2, 1]
    assert duplicate_chunk_sizes == [2, 2, 1]
    assert len(sessions.sessions) == 4  # three chunk transactions + final run record
    assert result.sources_checked == 1
    assert result.discovered == 5
    assert result.created == 5
    assert result.duplicates == 3
    assert result.failures == 0

    run_rows = [
        item
        for session in sessions.sessions
        for item in session.added
        if isinstance(item, SourceRun)
    ]
    assert len(run_rows) == 1
    assert run_rows[0].created_count == 5
    assert run_rows[0].duplicate_count == 3
    assert run_rows[0].status == "SUCCESS"
