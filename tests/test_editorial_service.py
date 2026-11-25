import os
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.agent import EditorialExecution
from app.ai.schemas import EditorialPackage
from app.config import Settings
from app.database.models import AIOutput, Article, ArticleStatus, NewsSource
from app.services.editorial import EditorialService


class FakeEditorialAgent:
    provider_name = "fake"
    model_name = "fake-model"

    async def create_editorial_package(self, **kwargs):
        package = EditorialPackage.model_validate(
            {
                "category": "economy",
                "language": "en",
                "summary": "Gazprom reported 15% growth in 2024.",
                "key_points": ["Gazprom reported 15% growth in 2024."],
                "entities": ["Gazprom"],
                "important_numbers": ["15%", "2024"],
                "channel_variants": {
                    "telegram": "Gazprom reported 15% growth in 2024.",
                    "brief": "Gazprom grew 15% in 2024.",
                },
                "caveats": [],
                "confidence": 0.9,
            }
        )
        return EditorialExecution(
            package=package,
            tool_trace=[{"tool": "check_word_count", "success": True}],
            attempt_count=1,
            input_tokens=40,
            output_tokens=80,
            duration_ms=150,
        )


@pytest.mark.asyncio
async def test_editorial_service_persists_draft_validation_and_execution_metadata():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for the PostgreSQL integration test")

    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    source_id = uuid.uuid4()
    article_id = uuid.uuid4()
    source_key = f"phase3-test-{source_id.hex}"
    try:
        async with sessions() as session, session.begin():
            source = NewsSource(
                id=source_id,
                source_key=source_key,
                name="Phase 3 test",
                kind="rss",
                base_url="https://example.com",
            )
            session.add(source)
            session.add(
                Article(
                    id=article_id,
                    source_id=source_id,
                    external_id="phase3-test-story",
                    canonical_url="https://example.com/news/phase3-test",
                    title="Gazprom exports",
                    content="Gazprom reported 15% growth in exports in 2024.",
                    source_metadata={"tags": ["#economy"]},
                )
            )

        settings = Settings(database_url=database_url)
        service = EditorialService(FakeEditorialAgent(), sessions, settings)
        queue = await service.pending_articles()
        assert any(item.id == article_id for item in queue)

        draft = await service.draft_article(article_id)
        assert draft.status == "NEEDS_REVIEW"
        assert draft.validation["passed"] is True

        async with sessions() as session:
            saved_article = await session.get(Article, article_id)
            output = await session.scalar(
                select(AIOutput).where(AIOutput.article_id == article_id)
            )
            assert saved_article is not None
            assert saved_article.status == ArticleStatus.SUMMARIZED.value
            assert output is not None
            assert output.status == "NEEDS_REVIEW"
            assert output.language == "en"
            assert output.prompt_version == "editorial-package-v1"
            assert output.tool_trace[0]["tool"] == "check_word_count"
            assert output.input_tokens == 40
            assert output.output_tokens == 80
            assert output.validation_json["human_review_required"] is True
    finally:
        async with sessions() as session, session.begin():
            await session.execute(delete(Article).where(Article.id == article_id))
            await session.execute(delete(NewsSource).where(NewsSource.id == source_id))
        await engine.dispose()
