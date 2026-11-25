import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.ai.agent import EditorialAgent, EditorialExecution
from app.ai.schemas import EditorialPackage
from app.ai.validation import validate_editorial_package
from app.config import Settings
from app.database.models import AIOutput, Article, ArticleStatus, NewsSource

logger = logging.getLogger(__name__)


class ArticleNotFoundError(LookupError):
    pass


class EditorialAlreadyRunningError(RuntimeError):
    pass


class EditorialGenerationError(RuntimeError):
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


class EditorialService:
    """Runs and persists an AI draft. It has no publication or approval operations."""

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
        safe_limit = max(1, min(limit, 20))
        async with self._session_factory() as session:
            rows = await session.execute(
                select(Article.id, Article.title, NewsSource.name, Article.canonical_url)
                .join(NewsSource, NewsSource.id == Article.source_id)
                .where(Article.status == ArticleStatus.DISCOVERED.value)
                .order_by(Article.created_at.asc())
                .limit(safe_limit)
            )
            return [
                DraftableArticle(
                    id=row.id,
                    title=row.title,
                    source_name=row.name,
                    canonical_url=row.canonical_url,
                )
                for row in rows
            ]

    async def draft_article(self, article_id: uuid.UUID) -> EditorialDraft:
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

            saved_output.content = execution.package.model_dump_json()
            saved_output.status = "NEEDS_REVIEW"
            saved_output.prompt_version = execution.prompt_version
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
