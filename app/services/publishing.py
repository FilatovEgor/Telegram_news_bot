import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.ai.schemas import EditorialPackage
from app.database.models import AIOutput, Article, ArticleStatus, EditorialAction, Publication
from app.services.editorial import ArticleNotFoundError, blocking_validation_checks

logger = logging.getLogger(__name__)


class PublicationNotAllowedError(ValueError):
    pass


class PublicationAlreadyAttemptedError(RuntimeError):
    def __init__(self, status: str) -> None:
        super().__init__(f"A publication attempt already exists with status {status}")
        self.status = status


@dataclass(slots=True, frozen=True)
class PublicationPayload:
    output_id: uuid.UUID
    article_id: uuid.UUID
    title: str
    source_url: str
    package: EditorialPackage


@dataclass(slots=True, frozen=True)
class PublicationAttempt(PublicationPayload):
    publication_id: uuid.UUID
    channel_id: str


class PublicationService:
    """Reserves and records explicit publication attempts; never auto-publishes."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def get_publishable(self, article_id: uuid.UUID) -> PublicationPayload:
        async with self._session_factory() as session:
            return await self._load_publishable(session, article_id, lock=False)

    async def _load_publishable(
        self,
        session,
        article_id: uuid.UUID,
        *,
        lock: bool,
    ) -> PublicationPayload:
        article_query = select(Article).where(Article.id == article_id)
        if lock:
            article_query = article_query.with_for_update()
        article = await session.scalar(article_query)
        if article is None:
            raise ArticleNotFoundError("Article was not found")
        if article.status != ArticleStatus.APPROVED.value:
            raise PublicationNotAllowedError("Only an explicitly approved article can be published")

        output_query = (
            select(AIOutput)
            .where(
                AIOutput.article_id == article_id,
                AIOutput.output_type == "editorial_package",
            )
            .order_by(AIOutput.created_at.desc(), AIOutput.id.desc())
            .limit(1)
        )
        if lock:
            output_query = output_query.with_for_update()
        output = await session.scalar(output_query)
        if output is None or output.status != "APPROVED":
            raise PublicationNotAllowedError("The latest editorial package is not approved")
        blockers = blocking_validation_checks(output.validation_json or {})
        if blockers:
            raise PublicationNotAllowedError("Approved package has failed blocking validation checks")

        return PublicationPayload(
            output_id=output.id,
            article_id=article.id,
            title=article.title,
            source_url=article.canonical_url,
            package=EditorialPackage.model_validate_json(output.content),
        )

    async def reserve_publication(
        self,
        article_id: uuid.UUID,
        channel_id: str,
        actor_telegram_id: int,
        expected_output_id: uuid.UUID,
    ) -> PublicationAttempt:
        async with self._session_factory() as session, session.begin():
            payload = await self._load_publishable(session, article_id, lock=True)
            if payload.output_id != expected_output_id:
                raise PublicationNotAllowedError(
                    "The approved draft changed after preview; review it again before publishing"
                )
            existing = await session.scalar(
                select(Publication)
                .where(
                    Publication.article_id == article_id,
                    Publication.channel_id == channel_id,
                )
                .with_for_update()
            )
            if existing is not None:
                raise PublicationAlreadyAttemptedError(existing.status)

            publication = Publication(
                article_id=article_id,
                channel_id=channel_id,
                status="SENDING",
            )
            session.add(publication)
            await session.flush()
            session.add(
                EditorialAction(
                    article_id=article_id,
                    actor_telegram_id=actor_telegram_id,
                    action="PUBLISH_REQUESTED",
                    details={
                        "publication_id": str(publication.id),
                        "output_id": str(payload.output_id),
                        "channel_id": channel_id,
                    },
                )
            )
            return PublicationAttempt(
                **{
                    "output_id": payload.output_id,
                    "article_id": payload.article_id,
                    "title": payload.title,
                    "source_url": payload.source_url,
                    "package": payload.package,
                    "publication_id": publication.id,
                    "channel_id": channel_id,
                }
            )

    async def mark_published(
        self,
        publication_id: uuid.UUID,
        message_id: int,
        actor_telegram_id: int,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            publication = await session.scalar(
                select(Publication)
                .where(Publication.id == publication_id)
                .with_for_update()
            )
            if publication is None:
                raise LookupError("Publication reservation was not found")
            if publication.status == "PUBLISHED":
                return
            if publication.status != "SENDING":
                raise ValueError(f"Publication reservation is in state {publication.status}")
            article = await session.get(Article, publication.article_id)
            if article is None:
                raise LookupError("Article for the publication was not found")

            publication.status = "PUBLISHED"
            publication.message_id = message_id
            publication.published_at = datetime.now(UTC)
            publication.error = None
            article.status = ArticleStatus.PUBLISHED.value
            session.add(
                EditorialAction(
                    article_id=article.id,
                    actor_telegram_id=actor_telegram_id,
                    action="PUBLISHED",
                    details={
                        "publication_id": str(publication.id),
                        "channel_id": publication.channel_id,
                        "message_id": message_id,
                    },
                )
            )

    async def mark_unknown(
        self,
        publication_id: uuid.UUID,
        actor_telegram_id: int,
        error_type: str,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            publication = await session.scalar(
                select(Publication)
                .where(Publication.id == publication_id)
                .with_for_update()
            )
            if publication is None or publication.status != "SENDING":
                return
            publication.status = "UNKNOWN"
            publication.error = f"Telegram send outcome is uncertain ({error_type})"
            session.add(
                EditorialAction(
                    article_id=publication.article_id,
                    actor_telegram_id=actor_telegram_id,
                    action="PUBLISH_UNCERTAIN",
                    details={
                        "publication_id": str(publication.id),
                        "channel_id": publication.channel_id,
                        "error_type": error_type,
                        "next_step": "Check the destination channel manually; do not retry automatically.",
                    },
                )
            )
