import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.ai.agent import EditorialAgent, TranslationExecution
from app.ai.schemas import EditorialPackage, TranslationPackage
from app.ai.validation import validate_translation_package
from app.config import Settings
from app.database.models import AIOutput, Article, EditorialAction, NewsSource, Publication
from app.services.editorial import ArticleNotFoundError, blocking_validation_checks
from app.services.pagination import CursorPage, decode_cursor, encode_cursor

logger = logging.getLogger(__name__)


class TranslationAlreadyRunningError(RuntimeError):
    pass


class TranslationGenerationError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class TranslationReviewItem:
    output_id: uuid.UUID
    article_id: uuid.UUID
    source_title: str
    source_name: str
    source_url: str
    package: TranslationPackage
    validation: dict[str, Any]
    status: str


class TranslationService:
    """Creates independently reviewable translations of approved Russian editorial packages."""

    TARGET_LANGUAGE = "en"

    def __init__(
        self,
        agent: EditorialAgent,
        session_factory: async_sessionmaker,
        settings: Settings,
    ) -> None:
        self._agent = agent
        self._session_factory = session_factory
        self._settings = settings

    async def translation_queue(
        self,
        language: str = "en",
        limit: int = 10,
    ) -> list[TranslationReviewItem]:
        page = await self.translation_queue_page(language=language, limit=limit)
        return page.items

    async def translation_queue_page(
        self,
        language: str = "en",
        limit: int = 10,
        cursor: str | None = None,
        *,
        direction: str = "next",
    ) -> CursorPage[TranslationReviewItem]:
        normalized = language.strip().casefold()
        if normalized != self.TARGET_LANGUAGE:
            raise ValueError("Only English translation review is enabled")
        safe_limit = max(1, min(limit, 50))
        decoded = decode_cursor(cursor)
        if direction not in {"next", "previous"} or (direction == "previous" and decoded is None):
            raise ValueError("Invalid pagination direction or cursor")
        latest_output_id = (
            select(AIOutput.id)
            .where(
                AIOutput.article_id == Article.id,
                AIOutput.output_type == "translation_package",
                AIOutput.language == normalized,
                AIOutput.status == "NEEDS_REVIEW",
            )
            .order_by(AIOutput.created_at.desc(), AIOutput.id.desc())
            .limit(1)
            .correlate(Article)
            .scalar_subquery()
        )
        statement = (
            select(Article, NewsSource, AIOutput)
            .join(NewsSource, NewsSource.id == Article.source_id)
            .join(AIOutput, AIOutput.id == latest_output_id)
            .where(AIOutput.status == "NEEDS_REVIEW")
        )
        if decoded is not None:
            operator = tuple_(AIOutput.created_at, AIOutput.id)
            boundary = tuple_(decoded[0], decoded[1])
            statement = statement.where(
                operator < boundary if direction == "previous" else operator > boundary
            )
        order = (
            (AIOutput.created_at.desc(), AIOutput.id.desc())
            if direction == "previous"
            else (AIOutput.created_at.asc(), AIOutput.id.asc())
        )
        async with self._session_factory() as session:
            rows = list(
                (await session.execute(statement.order_by(*order).limit(safe_limit + 1))).all()
            )
        has_more = len(rows) > safe_limit
        rows = rows[:safe_limit]
        if direction == "previous":
            rows.reverse()
        items = [
            TranslationReviewItem(
                output_id=output.id,
                article_id=article.id,
                source_title=article.title,
                source_name=source.name,
                source_url=article.canonical_url,
                package=TranslationPackage.model_validate_json(output.content),
                validation=output.validation_json or {},
                status=output.status,
            )
            for article, source, output in rows
        ]
        previous_cursor = encode_cursor(rows[0][2].created_at, rows[0][2].id) if rows and (
            direction == "next" and decoded is not None or direction == "previous" and has_more
        ) else None
        next_cursor = encode_cursor(rows[-1][2].created_at, rows[-1][2].id) if rows and (
            direction == "next" and has_more or direction == "previous" and decoded is not None
        ) else None
        return CursorPage(items, previous_cursor, next_cursor)

    async def get_review_item(self, article_id: uuid.UUID) -> TranslationReviewItem:
        async with self._session_factory() as session:
            row = await session.execute(
                select(Article, NewsSource)
                .join(NewsSource, NewsSource.id == Article.source_id)
                .where(Article.id == article_id)
            )
            result = row.first()
            if result is None:
                raise ArticleNotFoundError("Article was not found")
            article, source = result
            output = await session.scalar(
                select(AIOutput)
                .where(
                    AIOutput.article_id == article_id,
                    AIOutput.output_type == "translation_package",
                    AIOutput.language == self.TARGET_LANGUAGE,
                    AIOutput.status == "NEEDS_REVIEW",
                )
                .order_by(AIOutput.created_at.desc(), AIOutput.id.desc())
                .limit(1)
            )
            if output is None:
                raise ValueError("This article has no English translation awaiting review")
            return TranslationReviewItem(
                output_id=output.id,
                article_id=article.id,
                source_title=article.title,
                source_name=source.name,
                source_url=article.canonical_url,
                package=TranslationPackage.model_validate_json(output.content),
                validation=output.validation_json or {},
                status=output.status,
            )

    async def translate_article(
        self,
        article_id: uuid.UUID,
        target_language: str = "en",
        actor_telegram_id: int | None = None,
    ) -> TranslationReviewItem:
        language = target_language.strip().casefold()
        if language != self.TARGET_LANGUAGE:
            raise ValueError("Only Russian-to-English translation is enabled")
        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            article = await session.scalar(
                select(Article).where(Article.id == article_id).with_for_update()
            )
            if article is None:
                raise ArticleNotFoundError("Article was not found")

            source_output = await session.scalar(
                select(AIOutput)
                .where(
                    AIOutput.article_id == article_id,
                    AIOutput.output_type == "editorial_package",
                )
                .order_by(AIOutput.created_at.desc(), AIOutput.id.desc())
                .limit(1)
                .with_for_update()
            )
            if source_output is None or source_output.status != "APPROVED":
                raise ValueError(
                    "Approve the Russian editorial draft before requesting an English translation"
                )
            source_package = EditorialPackage.model_validate_json(source_output.content)
            source_language = source_package.language.casefold()
            if source_language not in {"ru", "russian"}:
                raise ValueError("The approved editorial package is not in Russian")

            active_output = await session.scalar(
                select(AIOutput)
                .where(
                    AIOutput.article_id == article_id,
                    AIOutput.output_type == "translation_package",
                    AIOutput.language == language,
                    AIOutput.status == "RUNNING",
                )
                .order_by(AIOutput.created_at.desc())
                .limit(1)
            )
            if active_output is not None:
                stale_after = timedelta(seconds=self._settings.ai_run_timeout_seconds * 2)
                if active_output.created_at is None or active_output.created_at > now - stale_after:
                    raise TranslationAlreadyRunningError(
                        "An English translation is already running for this article"
                    )
                active_output.status = "FAILED"
                active_output.validation_json = {
                    "passed": False,
                    "human_review_required": True,
                    "error": "A previous translation run did not finish and was marked stale",
                }

            previous_outputs = list(
                await session.scalars(
                    select(AIOutput)
                    .where(
                        AIOutput.article_id == article_id,
                        AIOutput.output_type == "translation_package",
                        AIOutput.language == language,
                    )
                    .order_by(AIOutput.created_at.desc())
                    .with_for_update()
                )
            )
            for previous in previous_outputs:
                prior_publication = await session.scalar(
                    select(Publication.id).where(Publication.ai_output_id == previous.id).limit(1)
                )
                if prior_publication is not None:
                    raise ValueError(
                        "An English translation already has a publication attempt; "
                        "check the channel before creating a replacement"
                    )

            source_title = article.title
            source_content = article.content
            source_url = article.canonical_url
            output = AIOutput(
                article_id=article_id,
                provider=self._agent.provider_name,
                model=self._agent.model_name,
                output_type="translation_package",
                language=language,
                content="",
                status="RUNNING",
                prompt_version="translation-package-v1",
                validation_json={},
                tool_trace=[],
                metadata_json={
                    "source_url": source_url,
                    "source_output_id": str(source_output.id),
                    "source_language": source_language,
                    "target_language": language,
                },
            )
            session.add(output)
            await session.flush()
            output_id = output.id

        try:
            execution: TranslationExecution = await self._agent.create_translation_package(
                title=source_title,
                content=source_content,
                source_package=source_package,
                target_language=language,
            )
            validation = validate_translation_package(
                execution.package,
                source_title=source_title,
                source_content=source_content,
                source_language="ru",
                target_language=language,
                source_url=source_url,
                max_summary_words=self._settings.ai_summary_max_words,
            )
        except Exception as exc:
            logger.exception("Translation generation failed for article %s", article_id)
            async with self._session_factory() as session, session.begin():
                failed_output = await session.get(AIOutput, output_id)
                if failed_output is not None:
                    failed_output.status = "FAILED"
                    failed_output.validation_json = {
                        "passed": False,
                        "human_review_required": True,
                        "error_type": type(exc).__name__,
                        "scope_note": "No translation package was produced; investigate before retrying.",
                    }
            raise TranslationGenerationError(
                "The English translation could not be generated. Check application logs."
            ) from exc

        async with self._session_factory() as session, session.begin():
            saved_output = await session.get(AIOutput, output_id)
            if saved_output is None:
                raise RuntimeError("Translation record disappeared while generation was running")
            superseded_ids: list[str] = []
            previous_outputs = list(
                await session.scalars(
                    select(AIOutput).where(
                        AIOutput.article_id == article_id,
                        AIOutput.output_type == "translation_package",
                        AIOutput.language == language,
                        AIOutput.id != output_id,
                        AIOutput.status.in_(["NEEDS_REVIEW", "APPROVED"]),
                    )
                )
            )
            for previous in previous_outputs:
                previous.status = "SUPERSEDED"
                superseded_ids.append(str(previous.id))
            saved_output.content = execution.package.model_dump_json()
            saved_output.status = "NEEDS_REVIEW"
            saved_output.prompt_version = execution.prompt_version
            saved_output.validation_json = validation
            saved_output.attempt_count = execution.attempt_count
            saved_output.duration_ms = execution.duration_ms
            saved_output.input_tokens = execution.input_tokens
            saved_output.output_tokens = execution.output_tokens
            saved_output.metadata_json = {
                "schema_version": "translation-package-v1",
                "source_url": source_url,
                "source_output_id": str(source_output.id),
                "source_language": "ru",
                "target_language": language,
                "scope_note": validation["scope_note"],
            }
            session.add(
                EditorialAction(
                    article_id=article_id,
                    actor_telegram_id=actor_telegram_id,
                    action="TRANSLATION_CREATED" if not superseded_ids else "TRANSLATION_REGENERATED",
                    details={
                        "output_id": str(output_id),
                        "source_output_id": str(source_output.id),
                        "language": language,
                        "superseded_output_ids": superseded_ids,
                        "validation_passed": bool(validation.get("passed")),
                    },
                )
            )

        return TranslationReviewItem(
            output_id=output_id,
            article_id=article_id,
            source_title=source_title,
            source_name="",
            source_url=source_url,
            package=execution.package,
            validation=validation,
            status="NEEDS_REVIEW",
        )

    async def edit_telegram_variant(
        self,
        article_id: uuid.UUID,
        text: str,
        actor_telegram_id: int,
    ) -> TranslationReviewItem:
        edited_text = text.strip()
        if not edited_text:
            raise ValueError("The replacement English Telegram text cannot be empty")
        if len(edited_text) > 3000:
            raise ValueError("The replacement English Telegram text must be at most 3000 characters")
        async with self._session_factory() as session, session.begin():
            article = await session.scalar(
                select(Article).where(Article.id == article_id).with_for_update()
            )
            if article is None:
                raise ArticleNotFoundError("Article was not found")
            output = await session.scalar(
                select(AIOutput)
                .where(
                    AIOutput.article_id == article_id,
                    AIOutput.output_type == "translation_package",
                    AIOutput.language == self.TARGET_LANGUAGE,
                    AIOutput.status == "NEEDS_REVIEW",
                )
                .order_by(AIOutput.created_at.desc(), AIOutput.id.desc())
                .limit(1)
                .with_for_update()
            )
            if output is None or output.status != "NEEDS_REVIEW":
                raise ValueError("Only an English translation awaiting review can be edited")
            package = TranslationPackage.model_validate_json(output.content)
            previous_text = package.channel_variants.telegram
            updated = TranslationPackage.model_validate(
                {
                    **package.model_dump(),
                    "channel_variants": {
                        **package.channel_variants.model_dump(),
                        "telegram": edited_text,
                    },
                }
            )
            validation = validate_translation_package(
                updated,
                source_title=article.title,
                source_content=article.content,
                source_language="ru",
                target_language=self.TARGET_LANGUAGE,
                source_url=article.canonical_url,
                max_summary_words=self._settings.ai_summary_max_words,
            )
            output.content = updated.model_dump_json()
            output.validation_json = validation
            output.metadata_json = {
                **output.metadata_json,
                "last_edited_by": str(actor_telegram_id),
                "last_edited_at": datetime.now(UTC).isoformat(),
            }
            session.add(
                EditorialAction(
                    article_id=article_id,
                    actor_telegram_id=actor_telegram_id,
                    action="TRANSLATION_EDITED",
                    details={
                        "output_id": str(output.id),
                        "language": self.TARGET_LANGUAGE,
                        "field": "channel_variants.telegram",
                        "before": previous_text,
                        "after": edited_text,
                        "validation_passed": bool(validation.get("passed")),
                    },
                )
            )
            source_name = await session.scalar(
                select(NewsSource.name).where(NewsSource.id == article.source_id)
            )
            return TranslationReviewItem(
                output_id=output.id,
                article_id=article.id,
                source_title=article.title,
                source_name=source_name or "Unknown source",
                source_url=article.canonical_url,
                package=updated,
                validation=validation,
                status=output.status,
            )

    async def approve_translation(
        self,
        article_id: uuid.UUID,
        actor_telegram_id: int,
    ) -> TranslationReviewItem:
        async with self._session_factory() as session, session.begin():
            article = await session.scalar(
                select(Article).where(Article.id == article_id).with_for_update()
            )
            if article is None:
                raise ArticleNotFoundError("Article was not found")
            output = await session.scalar(
                select(AIOutput)
                .where(
                    AIOutput.article_id == article_id,
                    AIOutput.output_type == "translation_package",
                    AIOutput.language == self.TARGET_LANGUAGE,
                    AIOutput.status == "NEEDS_REVIEW",
                )
                .order_by(AIOutput.created_at.desc(), AIOutput.id.desc())
                .limit(1)
                .with_for_update()
            )
            if output is None or output.status != "NEEDS_REVIEW":
                raise ValueError("Only the latest English translation awaiting review can be approved")
            blockers = blocking_validation_checks(output.validation_json or {})
            if blockers:
                names = ", ".join(str(item.get("name", "check")) for item in blockers[:5])
                raise ValueError(
                    f"Translation approval blocked by failed checks: {names}. Edit or regenerate first."
                )
            output.status = "APPROVED"
            package = TranslationPackage.model_validate_json(output.content)
            source_name = await session.scalar(
                select(NewsSource.name).where(NewsSource.id == article.source_id)
            )
            session.add(
                EditorialAction(
                    article_id=article_id,
                    actor_telegram_id=actor_telegram_id,
                    action="TRANSLATION_APPROVED",
                    details={
                        "output_id": str(output.id),
                        "language": self.TARGET_LANGUAGE,
                        "validation_warnings": [
                            str(check.get("name"))
                            for check in (output.validation_json or {}).get("checks", [])
                            if isinstance(check, dict)
                            and not check.get("passed", False)
                            and check.get("severity") == "warning"
                        ],
                    },
                )
            )
            return TranslationReviewItem(
                output_id=output.id,
                article_id=article.id,
                source_title=article.title,
                source_name=source_name or "Unknown source",
                source_url=article.canonical_url,
                package=package,
                validation=output.validation_json or {},
                status=output.status,
            )

    async def reject_translation(
        self,
        article_id: uuid.UUID,
        actor_telegram_id: int,
        reason: str = "Rejected by editor",
    ) -> None:
        clean_reason = reason.strip()[:1000] or "No reason supplied"
        async with self._session_factory() as session, session.begin():
            article = await session.scalar(
                select(Article).where(Article.id == article_id).with_for_update()
            )
            if article is None:
                raise ArticleNotFoundError("Article was not found")
            output = await session.scalar(
                select(AIOutput)
                .where(
                    AIOutput.article_id == article_id,
                    AIOutput.output_type == "translation_package",
                    AIOutput.language == self.TARGET_LANGUAGE,
                    AIOutput.status == "NEEDS_REVIEW",
                )
                .order_by(AIOutput.created_at.desc(), AIOutput.id.desc())
                .limit(1)
                .with_for_update()
            )
            if output is None or output.status != "NEEDS_REVIEW":
                raise ValueError("Only the latest English translation awaiting review can be rejected")
            output.status = "REJECTED"
            session.add(
                EditorialAction(
                    article_id=article_id,
                    actor_telegram_id=actor_telegram_id,
                    action="TRANSLATION_REJECTED",
                    details={
                        "output_id": str(output.id),
                        "language": self.TARGET_LANGUAGE,
                        "reason": clean_reason,
                    },
                )
            )
