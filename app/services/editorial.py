import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.ai.agent import EditorialAgent, EditorialExecution
from app.ai.schemas import EditorialPackage
from app.ai.validation import validate_editorial_package
from app.config import Settings
from app.services.pagination import CursorPage, decode_cursor, encode_cursor
from app.database.models import (
    AIOutput,
    Article,
    ArticleStatus,
    EditorialAction,
    NewsSource,
)

logger = logging.getLogger(__name__)


class ArticleNotFoundError(LookupError):
    pass


class EditorialAlreadyRunningError(RuntimeError):
    pass


class EditorialGenerationError(RuntimeError):
    pass


class EditorialValidationError(ValueError):
    pass


@dataclass(slots=True, frozen=True)
class DraftableArticle:
    id: uuid.UUID
    title: str
    source_name: str
    canonical_url: str


@dataclass(slots=True, frozen=True)
class EditorialDraft:
    output_id: uuid.UUID
    article_id: uuid.UUID
    title: str
    source_url: str
    package: EditorialPackage
    validation: dict[str, Any]
    provider: str
    model: str
    status: str


@dataclass(slots=True, frozen=True)
class EditorialReviewItem:
    output_id: uuid.UUID
    article_id: uuid.UUID
    title: str
    source_name: str
    source_url: str
    package: EditorialPackage
    validation: dict[str, Any]
    status: str


@dataclass(slots=True, frozen=True)
class EditorialHistoryEntry:
    action: str
    actor_telegram_id: int | None
    created_at: datetime | None
    details: dict[str, Any]


def blocking_validation_checks(validation: dict[str, Any]) -> list[dict[str, Any]]:
    checks = validation.get("checks")
    if not isinstance(checks, list):
        return [{"name": "validation_record", "details": "Validation checks are missing"}]
    return [
        check
        for check in checks
        if isinstance(check, dict)
        and not check.get("passed", False)
        and check.get("severity", "error") != "warning"
    ]


class EditorialService:
    """Generates drafts and records human moderation decisions; never publishes."""

    def __init__(
        self,
        agent: EditorialAgent,
        session_factory: async_sessionmaker,
        settings: Settings,
    ) -> None:
        self._agent = agent
        self._session_factory = session_factory
        self._settings = settings

    async def pending_articles(self, limit: int = 10) -> list[DraftableArticle]:
        page = await self.pending_articles_page(limit=limit)
        return page.items

    async def pending_articles_page(
        self,
        limit: int = 10,
        cursor: str | None = None,
        *,
        direction: str = "next",
    ) -> CursorPage[DraftableArticle]:
        safe_limit = max(1, min(limit, 50))
        decoded = decode_cursor(cursor)
        if direction not in {"next", "previous"} or (direction == "previous" and decoded is None):
            raise ValueError("Invalid pagination direction or cursor")
        statement = (
            select(
                Article.id,
                Article.title,
                NewsSource.name,
                Article.canonical_url,
                Article.created_at,
            )
            .join(NewsSource, NewsSource.id == Article.source_id)
            .where(Article.status == ArticleStatus.DISCOVERED.value)
        )
        if decoded is not None:
            operator = tuple_(Article.created_at, Article.id)
            boundary = tuple_(decoded[0], decoded[1])
            statement = statement.where(
                operator < boundary if direction == "previous" else operator > boundary
            )
        order = (
            (Article.created_at.desc(), Article.id.desc())
            if direction == "previous"
            else (Article.created_at.asc(), Article.id.asc())
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
            DraftableArticle(
                id=row.id,
                title=row.title,
                source_name=row.name,
                canonical_url=row.canonical_url,
            )
            for row in rows
        ]
        previous_cursor = encode_cursor(rows[0].created_at, rows[0].id) if rows and (
            direction == "previous" or decoded is not None
        ) else None
        next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id) if rows and (
            direction == "next" and has_more or direction == "previous" and decoded is not None
        ) else None
        return CursorPage(items, previous_cursor, next_cursor)

    async def review_queue(self, limit: int = 10) -> list[EditorialReviewItem]:
        page = await self.review_queue_page(limit=limit)
        return page.items

    async def review_queue_page(
        self,
        limit: int = 10,
        cursor: str | None = None,
        *,
        direction: str = "next",
    ) -> CursorPage[EditorialReviewItem]:
        safe_limit = max(1, min(limit, 50))
        decoded = decode_cursor(cursor)
        if direction not in {"next", "previous"} or (direction == "previous" and decoded is None):
            raise ValueError("Invalid pagination direction or cursor")
        latest_output_id = (
            select(AIOutput.id)
            .where(
                AIOutput.article_id == Article.id,
                AIOutput.output_type == "editorial_package",
            )
            .order_by(AIOutput.created_at.desc(), AIOutput.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        statement = (
            select(Article, NewsSource, AIOutput)
            .join(NewsSource, NewsSource.id == Article.source_id)
            .join(AIOutput, AIOutput.id == latest_output_id)
            .where(
                Article.status == ArticleStatus.SUMMARIZED.value,
                AIOutput.status == "NEEDS_REVIEW",
            )
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
            EditorialReviewItem(
                output_id=output.id,
                article_id=article.id,
                title=article.title,
                source_name=source.name,
                source_url=article.canonical_url,
                package=EditorialPackage.model_validate_json(output.content),
                validation=output.validation_json or {},
                status=output.status,
            )
            for article, source, output in rows
        ]
        previous_cursor = encode_cursor(rows[0][2].created_at, rows[0][2].id) if rows and (
            direction == "previous" or decoded is not None
        ) else None
        next_cursor = encode_cursor(rows[-1][2].created_at, rows[-1][2].id) if rows and (
            direction == "next" and has_more or direction == "previous" and decoded is not None
        ) else None
        return CursorPage(items, previous_cursor, next_cursor)

    async def get_review_item(self, article_id: uuid.UUID) -> EditorialReviewItem:
        async with self._session_factory() as session:
            article_data = await session.execute(
                select(Article, NewsSource)
                .join(NewsSource, NewsSource.id == Article.source_id)
                .where(Article.id == article_id)
            )
            row = article_data.first()
            if row is None:
                raise ArticleNotFoundError("Article was not found")
            article, source = row
            output = await session.scalar(
                select(AIOutput)
                .where(
                    AIOutput.article_id == article_id,
                    AIOutput.output_type == "editorial_package",
                )
                .order_by(AIOutput.created_at.desc(), AIOutput.id.desc())
                .limit(1)
            )
            if (
                article.status != ArticleStatus.SUMMARIZED.value
                or output is None
                or output.status != "NEEDS_REVIEW"
            ):
                raise ValueError("This article does not have a draft awaiting review")
            return EditorialReviewItem(
                output_id=output.id,
                article_id=article.id,
                title=article.title,
                source_name=source.name,
                source_url=article.canonical_url,
                package=EditorialPackage.model_validate_json(output.content),
                validation=output.validation_json or {},
                status=output.status,
            )

    async def draft_article(
        self,
        article_id: uuid.UUID,
        actor_telegram_id: int | None = None,
    ) -> EditorialDraft:
        now = datetime.now(UTC)
        async with self._session_factory() as session, session.begin():
            article = await session.scalar(
                select(Article).where(Article.id == article_id).with_for_update()
            )
            if article is None:
                raise ArticleNotFoundError("Article was not found")
            if article.status not in {
                ArticleStatus.DISCOVERED.value,
                ArticleStatus.SUMMARIZED.value,
            }:
                raise ValueError(f"Article status {article.status} cannot be drafted")

            active_output = await session.scalar(
                select(AIOutput)
                .where(
                    AIOutput.article_id == article_id,
                    AIOutput.output_type == "editorial_package",
                    AIOutput.status == "RUNNING",
                )
                .order_by(AIOutput.created_at.desc())
                .limit(1)
            )
            if active_output is not None:
                stale_after = timedelta(seconds=self._settings.ai_run_timeout_seconds * 2)
                if active_output.created_at is None or active_output.created_at > now - stale_after:
                    raise EditorialAlreadyRunningError("An editorial draft is already running")
                active_output.status = "FAILED"
                active_output.validation_json = {
                    "passed": False,
                    "human_review_required": True,
                    "error": "A previous editorial run did not finish and was marked stale",
                }

            tags_value = article.source_metadata.get("tags", [])
            tags = [str(tag) for tag in tags_value] if isinstance(tags_value, list) else []
            title = article.title
            source_url = article.canonical_url
            source_content = article.content
            output = AIOutput(
                article_id=article_id,
                provider=self._agent.provider_name,
                model=self._agent.model_name,
                output_type="editorial_package",
                content="",
                status="RUNNING",
                prompt_version="editorial-package-v1",
                validation_json={},
                tool_trace=[],
                metadata_json={"source_url": source_url, "schema_version": "editorial-package-v1"},
            )
            session.add(output)
            await session.flush()
            output_id = output.id

        try:
            execution: EditorialExecution = await self._agent.create_editorial_package(
                title=title,
                content=source_content,
                source_url=source_url,
                tags=tags,
            )
            validation = validate_editorial_package(
                execution.package,
                source_title=title,
                source_content=source_content,
                source_url=source_url,
                max_summary_words=self._settings.ai_summary_max_words,
            )
        except Exception as exc:
            logger.exception("Editorial generation failed for article %s", article_id)
            async with self._session_factory() as session, session.begin():
                failed_output = await session.get(AIOutput, output_id)
                if failed_output is not None:
                    failed_output.status = "FAILED"
                    failed_output.validation_json = {
                        "passed": False,
                        "human_review_required": True,
                        "error_type": type(exc).__name__,
                        "scope_note": "No editorial package was produced; retry after investigating the error.",
                    }
                    failed_output.metadata_json = {
                        **failed_output.metadata_json,
                        "error_type": type(exc).__name__,
                    }
            raise EditorialGenerationError(
                "The AI editor could not complete this draft. Check application logs."
            ) from exc

        async with self._session_factory() as session, session.begin():
            saved_output = await session.get(AIOutput, output_id)
            saved_article = await session.get(Article, article_id)
            if saved_output is None or saved_article is None:
                raise RuntimeError("Editorial records disappeared while generation was running")

            previous_outputs = list(
                await session.scalars(
                    select(AIOutput).where(
                        AIOutput.article_id == article_id,
                        AIOutput.output_type == "editorial_package",
                        AIOutput.status == "NEEDS_REVIEW",
                    )
                )
            )
            previous_ids = [str(item.id) for item in previous_outputs]
            for previous in previous_outputs:
                previous.status = "SUPERSEDED"

            saved_output.content = execution.package.model_dump_json()
            saved_output.status = "NEEDS_REVIEW"
            saved_output.prompt_version = execution.prompt_version
            saved_output.language = execution.package.language.casefold()
            saved_output.validation_json = validation
            saved_output.tool_trace = execution.tool_trace
            saved_output.attempt_count = execution.attempt_count
            saved_output.duration_ms = execution.duration_ms
            saved_output.input_tokens = execution.input_tokens
            saved_output.output_tokens = execution.output_tokens
            saved_output.metadata_json = {
                "schema_version": "editorial-package-v1",
                "source_url": source_url,
                "confidence": execution.package.confidence,
                "scope_note": validation["scope_note"],
            }
            saved_article.status = ArticleStatus.SUMMARIZED.value
            session.add(
                EditorialAction(
                    article_id=article_id,
                    actor_telegram_id=actor_telegram_id,
                    action="REGENERATED" if previous_ids else "DRAFT_CREATED",
                    details={
                        "output_id": str(output_id),
                        "superseded_output_ids": previous_ids,
                        "validation_passed": bool(validation.get("passed")),
                    },
                )
            )

        return EditorialDraft(
            output_id=output_id,
            article_id=article_id,
            title=title,
            source_url=source_url,
            package=execution.package,
            validation=validation,
            provider=self._agent.provider_name,
            model=self._agent.model_name,
            status="NEEDS_REVIEW",
        )

    async def edit_telegram_variant(
        self,
        article_id: uuid.UUID,
        text: str,
        actor_telegram_id: int,
    ) -> EditorialReviewItem:
        edited_text = text.strip()
        if not edited_text:
            raise ValueError("The replacement Telegram text cannot be empty")
        if len(edited_text) > 3000:
            raise ValueError("The replacement Telegram text must be at most 3000 characters")

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
                    AIOutput.output_type == "editorial_package",
                )
                .order_by(AIOutput.created_at.desc(), AIOutput.id.desc())
                .limit(1)
                .with_for_update()
            )
            if (
                article.status != ArticleStatus.SUMMARIZED.value
                or output is None
                or output.status != "NEEDS_REVIEW"
            ):
                raise ValueError("Only a draft awaiting review can be edited")

            package = EditorialPackage.model_validate_json(output.content)
            previous_text = package.channel_variants.telegram
            updated_package = EditorialPackage.model_validate(
                {
                    **package.model_dump(),
                    "channel_variants": {
                        **package.channel_variants.model_dump(),
                        "telegram": edited_text,
                    },
                }
            )
            validation = validate_editorial_package(
                updated_package,
                source_title=article.title,
                source_content=article.content,
                source_url=article.canonical_url,
                max_summary_words=self._settings.ai_summary_max_words,
            )
            output.content = updated_package.model_dump_json()
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
                    action="EDITED",
                    details={
                        "output_id": str(output.id),
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
            return EditorialReviewItem(
                output_id=output.id,
                article_id=article.id,
                title=article.title,
                source_name=source_name or "Unknown source",
                source_url=article.canonical_url,
                package=updated_package,
                validation=validation,
                status=output.status,
            )

    async def approve_article(
        self,
        article_id: uuid.UUID,
        actor_telegram_id: int,
    ) -> EditorialReviewItem:
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
                    AIOutput.output_type == "editorial_package",
                )
                .order_by(AIOutput.created_at.desc(), AIOutput.id.desc())
                .limit(1)
                .with_for_update()
            )
            if (
                article.status != ArticleStatus.SUMMARIZED.value
                or output is None
                or output.status != "NEEDS_REVIEW"
            ):
                raise ValueError("Only the latest draft awaiting review can be approved")
            validation = output.validation_json or {}
            blockers = blocking_validation_checks(validation)
            if blockers:
                names = ", ".join(str(item.get("name", "check")) for item in blockers[:5])
                raise EditorialValidationError(
                    f"Approval blocked by failed validation checks: {names}. Edit or regenerate first."
                )

            output.status = "APPROVED"
            article.status = ArticleStatus.APPROVED.value
            package = EditorialPackage.model_validate_json(output.content)
            source_name = await session.scalar(
                select(NewsSource.name).where(NewsSource.id == article.source_id)
            )
            session.add(
                EditorialAction(
                    article_id=article_id,
                    actor_telegram_id=actor_telegram_id,
                    action="APPROVED",
                    details={
                        "output_id": str(output.id),
                        "validation_warnings": [
                            str(check.get("name"))
                            for check in validation.get("checks", [])
                            if isinstance(check, dict)
                            and not check.get("passed", False)
                            and check.get("severity") == "warning"
                        ],
                    },
                )
            )
            return EditorialReviewItem(
                output_id=output.id,
                article_id=article.id,
                title=article.title,
                source_name=source_name or "Unknown source",
                source_url=article.canonical_url,
                package=package,
                validation=validation,
                status=output.status,
            )

    async def reject_article(
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
                    AIOutput.output_type == "editorial_package",
                )
                .order_by(AIOutput.created_at.desc(), AIOutput.id.desc())
                .limit(1)
                .with_for_update()
            )
            if (
                article.status != ArticleStatus.SUMMARIZED.value
                or output is None
                or output.status != "NEEDS_REVIEW"
            ):
                raise ValueError("Only the latest draft awaiting review can be rejected")
            output.status = "REJECTED"
            article.status = ArticleStatus.REJECTED.value
            session.add(
                EditorialAction(
                    article_id=article_id,
                    actor_telegram_id=actor_telegram_id,
                    action="REJECTED",
                    details={"output_id": str(output.id), "reason": clean_reason},
                )
            )

    async def action_history(
        self,
        article_id: uuid.UUID,
        limit: int = 20,
    ) -> list[EditorialHistoryEntry]:
        safe_limit = max(1, min(limit, 50))
        async with self._session_factory() as session:
            article_exists = await session.scalar(
                select(Article.id).where(Article.id == article_id)
            )
            if article_exists is None:
                raise ArticleNotFoundError("Article was not found")
            actions = await session.scalars(
                select(EditorialAction)
                .where(EditorialAction.article_id == article_id)
                .order_by(EditorialAction.created_at.desc(), EditorialAction.id.desc())
                .limit(safe_limit)
            )
            return [
                EditorialHistoryEntry(
                    action=item.action,
                    actor_telegram_id=item.actor_telegram_id,
                    created_at=item.created_at,
                    details=item.details or {},
                )
                for item in actions
            ]
