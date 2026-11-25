import os
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.schemas import EditorialPackage
from app.ai.validation import validate_editorial_package
from app.config import Settings
from app.database.models import (
    AIOutput,
    Article,
    ArticleStatus,
    EditorialAction,
    NewsSource,
    Publication,
)
from app.services.editorial import EditorialService, EditorialValidationError
from app.services.publishing import (
    PublicationAlreadyAttemptedError,
    PublicationService,
)


def _package() -> EditorialPackage:
    return EditorialPackage.model_validate(
        {
            "category": "economy",
            "language": "en",
            "summary": "Gazprom reported 15% growth in exports in 2024.",
            "key_points": ["Gazprom reported 15% growth in exports in 2024."],
            "entities": ["Gazprom"],
            "important_numbers": ["15%", "2024"],
            "channel_variants": {
                "telegram": "Gazprom reported 15% growth in exports in 2024.",
                "brief": "Gazprom grew 15% in 2024.",
            },
            "caveats": [],
            "confidence": 0.9,
        }
    )


async def _seed_review_article(sessions, *, failing_numeric_check: bool = False):
    source_id = uuid.uuid4()
    article_id = uuid.uuid4()
    source_key = f"phase4-test-{source_id.hex}"
    package = _package()
    source_title = "Gazprom exports"
    source_content = "Gazprom reported 15% growth in exports in 2024."
    validation = validate_editorial_package(
        package,
        source_title=source_title,
        source_content=source_content,
        source_url="https://example.com/news/phase4",
    )
    if failing_numeric_check:
        validation["checks"][1]["passed"] = False
        validation["checks"][1]["details"] = "Test-only blocking validation failure"
        validation["passed"] = False

    async with sessions() as session, session.begin():
        session.add(
            NewsSource(
                id=source_id,
                source_key=source_key,
                name="Phase 4 integration test",
                kind="rss",
                base_url="https://example.com",
            )
        )
        session.add(
            Article(
                id=article_id,
                source_id=source_id,
                external_id="phase4-test-story",
                canonical_url="https://example.com/news/phase4",
                title=source_title,
                content=source_content,
                status=ArticleStatus.SUMMARIZED.value,
                source_metadata={},
            )
        )
        session.add(
            AIOutput(
                article_id=article_id,
                provider="test",
                model="test-model",
                output_type="editorial_package",
                content=package.model_dump_json(),
                status="NEEDS_REVIEW",
                prompt_version="editorial-package-v1",
                validation_json=validation,
                tool_trace=[],
                metadata_json={"source_url": "https://example.com/news/phase4"},
            )
        )
    return source_id, article_id


@pytest.mark.asyncio
async def test_review_approval_and_publication_are_audited_and_idempotent():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for the PostgreSQL integration test")

    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    source_id, article_id = await _seed_review_article(sessions)
    settings = Settings(database_url=database_url)
    editorial = EditorialService(agent=None, session_factory=sessions, settings=settings)
    publishing = PublicationService(sessions)
    actor_id = 123456789
    try:
        item = await editorial.get_review_item(article_id)
        assert item.status == "NEEDS_REVIEW"

        edited = await editorial.edit_telegram_variant(
            article_id,
            "Gazprom reported 15% export growth in 2024.",
            actor_telegram_id=actor_id,
        )
        assert edited.package.channel_variants.telegram.startswith("Gazprom reported")

        approved = await editorial.approve_article(article_id, actor_telegram_id=actor_id)
        assert approved.status == "APPROVED"

        payload = await publishing.get_publishable(article_id)
        attempt = await publishing.reserve_publication(
            article_id,
            "@phase4_test_channel",
            actor_telegram_id=actor_id,
            expected_output_id=payload.output_id,
        )
        assert attempt.article_id == article_id
        assert attempt.channel_id == "@phase4_test_channel"

        with pytest.raises(PublicationAlreadyAttemptedError) as error:
            await publishing.reserve_publication(
                article_id,
                "@phase4_test_channel",
                actor_telegram_id=actor_id,
                expected_output_id=payload.output_id,
            )
        assert error.value.status == "SENDING"

        await publishing.mark_published(
            attempt.publication_id,
            message_id=77,
            actor_telegram_id=actor_id,
        )
        async with sessions() as session:
            article = await session.get(Article, article_id)
            publication = await session.scalar(
                select(Publication).where(Publication.id == attempt.publication_id)
            )
            assert article is not None
            assert article.status == ArticleStatus.PUBLISHED.value
            assert publication is not None
            assert publication.status == "PUBLISHED"
            assert publication.message_id == 77

        history = await editorial.action_history(article_id)
        actions = [entry.action for entry in history]
        assert "EDITED" in actions
        assert "APPROVED" in actions
        assert "PUBLISH_REQUESTED" in actions
        assert "PUBLISHED" in actions
        assert all(entry.actor_telegram_id == actor_id for entry in history)
    finally:
        async with sessions() as session, session.begin():
            await session.execute(delete(Article).where(Article.id == article_id))
            await session.execute(delete(NewsSource).where(NewsSource.id == source_id))
        await engine.dispose()


@pytest.mark.asyncio
async def test_approval_is_blocked_by_error_level_validation_failure():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for the PostgreSQL integration test")

    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    source_id, article_id = await _seed_review_article(
        sessions,
        failing_numeric_check=True,
    )
    settings = Settings(database_url=database_url)
    editorial = EditorialService(agent=None, session_factory=sessions, settings=settings)
    try:
        with pytest.raises(EditorialValidationError):
            await editorial.approve_article(article_id, actor_telegram_id=123456789)

        async with sessions() as session:
            article = await session.get(Article, article_id)
            output = await session.scalar(
                select(AIOutput).where(AIOutput.article_id == article_id)
            )
            assert article is not None
            assert article.status == ArticleStatus.SUMMARIZED.value
            assert output is not None
            assert output.status == "NEEDS_REVIEW"
            actions = await session.scalars(
                select(EditorialAction).where(EditorialAction.article_id == article_id)
            )
            assert "APPROVED" not in [action.action for action in actions]
    finally:
        async with sessions() as session, session.begin():
            await session.execute(delete(Article).where(Article.id == article_id))
            await session.execute(delete(NewsSource).where(NewsSource.id == source_id))
        await engine.dispose()
