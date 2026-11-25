import os
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.agent import EditorialAgent, TranslationExecution
from app.ai.schemas import EditorialPackage, TranslationPackage
from app.ai.validation import validate_translation_package
from app.config import Settings
from app.database.models import (
    AIOutput,
    Article,
    ArticleStatus,
    NewsSource,
    Publication,
)
from app.services.publishing import PublicationNotAllowedError, PublicationService
from app.services.translation import TranslationGenerationError, TranslationService


def _translation_package(**overrides) -> TranslationPackage:
    values = {
        "source_language": "ru",
        "language": "en",
        "title": "Gazprom Reports 15% Growth in Gas Exports",
        "category": "energy",
        "summary": "Gazprom reported 15% growth in gas exports in 2024.",
        "key_points": ["The company reported 15% growth in 2024."],
        "entities": ["Газпром"],
        "important_numbers": ["15%", "2024"],
        "channel_variants": {
            "telegram": "Gazprom reported 15% growth in gas exports in 2024.",
            "brief": "Gazprom exports grew 15% in 2024.",
        },
        "caveats": [],
        "confidence": 0.91,
    }
    values.update(overrides)
    return TranslationPackage.model_validate(values)


def _source_package() -> EditorialPackage:
    return EditorialPackage.model_validate(
        {
            "category": "energy",
            "language": "ru",
            "summary": "Газпром сообщил о росте экспорта газа на 15% в 2024 году.",
            "key_points": ["Экспорт газа вырос на 15% в 2024 году."],
            "entities": ["Газпром"],
            "important_numbers": ["15%", "2024"],
            "channel_variants": {
                "telegram": "Газпром сообщил о росте экспорта газа на 15% в 2024 году.",
                "brief": "Экспорт газа вырос на 15% в 2024 году.",
            },
            "caveats": [],
            "confidence": 0.9,
        }
    )


def test_translation_validation_preserves_numbers_and_language_codes():
    result = validate_translation_package(
        _translation_package(),
        source_title="Газпром увеличил экспорт газа на 15%",
        source_content="Компания сообщила о росте экспорта газа на 15% в 2024 году.",
        source_language="ru",
        target_language="en",
        source_url="https://example.com/news/translation",
    )
    assert result["passed"] is True
    assert result["human_review_required"] is True


def test_translation_validation_blocks_added_numbers_and_wrong_language():
    result = validate_translation_package(
        _translation_package(
            source_language="de",
            summary="Gazprom reported 95% growth in gas exports in 2024.",
            important_numbers=["95%", "2024"],
            channel_variants={
                "telegram": "Gazprom reported 95% growth in gas exports in 2024.",
                "brief": "Gazprom exports grew 95% in 2024.",
            },
        ),
        source_title="Газпром увеличил экспорт газа на 15%",
        source_content="Компания сообщила о росте экспорта газа на 15% в 2024 году.",
        source_language="ru",
        target_language="en",
        source_url="https://example.com/news/translation",
    )
    assert result["passed"] is False
    assert result["unsupported_numbers"] == ["95%"]
    failed = {item["name"] for item in result["checks"] if not item["passed"]}
    assert "target_language" in failed
    assert "numeric_preservation" in failed


class TranslationResponseProvider:
    name = "test"
    model = "test-model"

    async def create_chat_completion(self, **kwargs):
        package = _translation_package().model_dump_json()
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=package, tool_calls=[]))],
            usage=SimpleNamespace(prompt_tokens=120, completion_tokens=140),
        )

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_agent_generates_a_separate_english_translation_package():
    agent = EditorialAgent(TranslationResponseProvider())
    result = await agent.create_translation_package(
        title="Газпром увеличил экспорт газа на 15%",
        content="Компания сообщила о росте экспорта газа на 15% в 2024 году.",
        source_package=_source_package(),
        target_language="en",
    )
    assert result.package.title.startswith("Gazprom Reports")
    assert result.package.language == "en"
    assert result.package.source_language == "ru"
    assert result.attempt_count == 1
    assert result.input_tokens == 120
    assert result.output_tokens == 140


class FakeTranslationAgent:
    provider_name = "fake"
    model_name = "fake-translation-model"

    def __init__(self):
        self.fail_next = False

    async def create_translation_package(self, **kwargs):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("simulated translation failure")
        return TranslationExecution(
            package=_translation_package(),
            attempt_count=1,
            input_tokens=80,
            output_tokens=100,
            duration_ms=90,
        )


@pytest.mark.asyncio
async def test_russian_and_english_versions_have_independent_approvals_and_publications():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for the PostgreSQL integration test")

    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    source_id = uuid.uuid4()
    article_id = uuid.uuid4()
    source_key = f"phase5-translation-{source_id.hex}"
    title = "Газпром увеличил экспорт газа на 15%"
    content = "Компания сообщила о росте экспорта газа на 15% в 2024 году."
    source_package = _source_package()
    source_validation = {
        "passed": True,
        "human_review_required": True,
        "checks": [
            {"name": "numeric_consistency", "passed": True, "severity": "error"},
        ],
    }
    actor_id = 987654321
    publishing = PublicationService(sessions)
    fake_agent = FakeTranslationAgent()
    translation_service = TranslationService(
        fake_agent,
        sessions,
        Settings(database_url=database_url),
    )
    try:
        async with sessions() as session, session.begin():
            session.add(
                NewsSource(
                    id=source_id,
                    source_key=source_key,
                    name="Phase 5 Russian source",
                    kind="rss",
                    base_url="https://example.com",
                )
            )
            session.add(
                Article(
                    id=article_id,
                    source_id=source_id,
                    external_id="phase5-story",
                    canonical_url="https://example.com/news/phase5",
                    title=title,
                    content=content,
                    status=ArticleStatus.APPROVED.value,
                    source_metadata={},
                )
            )
            session.add(
                AIOutput(
                    article_id=article_id,
                    provider="test",
                    model="test-model",
                    output_type="editorial_package",
                    language="ru",
                    content=source_package.model_dump_json(),
                    status="APPROVED",
                    prompt_version="editorial-package-v1",
                    validation_json=source_validation,
                    tool_trace=[],
                    metadata_json={"source_url": "https://example.com/news/phase5"},
                )
            )

        russian_payload = await publishing.get_publishable(article_id, language="ru")
        russian_attempt = await publishing.reserve_publication(
            article_id,
            "@phase5_ru_channel",
            actor_telegram_id=actor_id,
            expected_output_id=russian_payload.output_id,
            language="ru",
        )
        await publishing.mark_published(
            russian_attempt.publication_id,
            message_id=501,
            actor_telegram_id=actor_id,
        )

        translation = await translation_service.translate_article(
            article_id,
            target_language="en",
            actor_telegram_id=actor_id,
        )
        assert translation.status == "NEEDS_REVIEW"
        assert translation.package.language == "en"
        assert translation.validation["passed"] is True

        fake_agent.fail_next = True
        with pytest.raises(TranslationGenerationError, match="could not be generated"):
            await translation_service.translate_article(
                article_id,
                target_language="en",
                actor_telegram_id=actor_id,
            )
        queue_after_failure = await translation_service.translation_queue()
        assert [item.output_id for item in queue_after_failure] == [translation.output_id]

        replacement = await translation_service.translate_article(
            article_id,
            target_language="en",
            actor_telegram_id=actor_id,
        )
        assert replacement.status == "NEEDS_REVIEW"
        queue = await translation_service.translation_queue()
        assert [item.output_id for item in queue] == [replacement.output_id]

        edited = await translation_service.edit_telegram_variant(
            article_id,
            "Gazprom reported 15% growth in gas exports in 2024.",
            actor_telegram_id=actor_id,
        )
        assert edited.package.channel_variants.telegram.startswith("Gazprom")

        approved_translation = await translation_service.approve_translation(
            article_id,
            actor_telegram_id=actor_id,
        )
        assert approved_translation.status == "APPROVED"

        english_payload = await publishing.get_publishable(article_id, language="en")
        assert english_payload.title == "Gazprom Reports 15% Growth in Gas Exports"
        english_attempt = await publishing.reserve_publication(
            article_id,
            "@phase5_en_channel",
            actor_telegram_id=actor_id,
            expected_output_id=english_payload.output_id,
            language="en",
        )
        await publishing.mark_published(
            english_attempt.publication_id,
            message_id=502,
            actor_telegram_id=actor_id,
        )

        with pytest.raises(PublicationNotAllowedError):
            await publishing.get_publishable(article_id, language="de")

        async with sessions() as session:
            article = await session.get(Article, article_id)
            outputs = list(
                await session.scalars(
                    select(AIOutput)
                    .where(AIOutput.article_id == article_id)
                    .order_by(AIOutput.created_at.asc())
                )
            )
            publications = list(
                await session.scalars(
                    select(Publication)
                    .where(Publication.article_id == article_id)
                    .order_by(Publication.language.asc())
                )
            )
            assert article is not None
            assert article.status == ArticleStatus.PUBLISHED.value
            assert [
                (item.output_type, item.language, item.status)
                for item in outputs
            ].count(("editorial_package", "ru", "APPROVED")) == 1
            assert [
                (item.output_type, item.language, item.status)
                for item in outputs
            ].count(("translation_package", "en", "APPROVED")) == 1
            assert [
                item.status for item in outputs if item.output_type == "translation_package"
            ].count("SUPERSEDED") == 1
            assert {item.language for item in publications} == {"ru", "en"}
            assert all(item.ai_output_id is not None for item in publications)

        assert russian_attempt.channel_id == "@phase5_ru_channel"
        assert english_attempt.channel_id == "@phase5_en_channel"
    finally:
        async with sessions() as session, session.begin():
            await session.execute(delete(Article).where(Article.id == article_id))
            await session.execute(delete(NewsSource).where(NewsSource.id == source_id))
        await engine.dispose()
