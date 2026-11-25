import html
import logging
import uuid

from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import Message

from app.ai.tools import format_telegram_draft
from app.config import Settings
from app.services.editorial import (
    ArticleNotFoundError,
    EditorialAlreadyRunningError,
    EditorialGenerationError,
    EditorialService,
)

logger = logging.getLogger(__name__)
router = Router(name="editorial")


def _is_admin(message: Message, settings: Settings) -> bool:
    return message.from_user is not None and message.from_user.id in settings.admin_id_set


@router.message(Command("drafts"))
async def drafts_command(
    message: Message,
    settings: Settings,
    editorial_service: EditorialService,
) -> None:
    if not _is_admin(message, settings):
        await message.answer("This command is available to configured administrators only.")
        return

    try:
        articles = await editorial_service.pending_articles(limit=10)
    except Exception:
        logger.exception("Could not list articles awaiting editorial drafts")
        await message.answer("Could not load the article queue. Check application logs.")
        return

    if not articles:
        await message.answer("No newly discovered articles are waiting for an AI draft.")
        return

    lines = ["<b>Articles awaiting editorial drafts</b>"]
    for article in articles:
        lines.append(
            f"\n<b>{html.escape(article.title)}</b>"
            f"\nSource: {html.escape(article.source_name)}"
            f"\n<code>{article.id}</code>"
            f"\nUse: <code>/draft {article.id}</code>"
        )
    await message.answer("\n".join(lines))


@router.message(Command("draft"))
async def draft_command(
    message: Message,
    command: CommandObject,
    settings: Settings,
    editorial_service: EditorialService,
) -> None:
    if not _is_admin(message, settings):
        await message.answer("This command is available to configured administrators only.")
        return

    raw_id = (command.args or "").strip()
    try:
        article_id = uuid.UUID(raw_id)
    except (ValueError, AttributeError):
        await message.answer("Usage: <code>/draft ARTICLE_UUID</code>. Get IDs with /drafts.")
        return

    await message.answer("Preparing an AI editorial draft. This does not approve or publish it…")
    try:
        draft = await editorial_service.draft_article(article_id)
    except ArticleNotFoundError:
        await message.answer("Article was not found.")
        return
    except EditorialAlreadyRunningError:
        await message.answer("An AI editorial draft is already running for this article.")
        return
    except EditorialGenerationError as exc:
        await message.answer(html.escape(str(exc)))
        return
    except ValueError as exc:
        await message.answer(html.escape(str(exc)))
        return
    except Exception:
        logger.exception("Unexpected editorial processing error for article %s", article_id)
        await message.answer("Editorial processing failed. Check application logs.")
        return

    check_items = draft.validation.get("checks", [])
    failed_checks = [
        item for item in check_items
        if isinstance(item, dict) and not item.get("passed", False)
    ]
    validation_state = (
        "passed" if not failed_checks else f"{len(failed_checks)} check(s) need attention"
    )
    header = (
        "<b>AI editorial package created — HUMAN REVIEW REQUIRED</b>\n"
        f"Category: {html.escape(draft.package.category)}\n"
        f"Language: {html.escape(draft.package.language)}\n"
        f"Provider/model: {html.escape(draft.provider)} / {html.escape(draft.model)}\n"
        f"Confidence (AI estimate): {draft.package.confidence:.2f}\n"
        f"Validation: {validation_state}\n"
        f"Summary: {len(draft.package.summary.split())} words"
    )
    await message.answer(header)

    if failed_checks:
        notes = ["<b>Validation warnings</b>"]
        for item in failed_checks[:5]:
            notes.append(
                f"• {html.escape(str(item.get('name', 'check')))}: "
                f"{html.escape(str(item.get('details', 'Needs review')))}"
            )
        await message.answer("\n".join(notes))

    telegram_preview = await format_telegram_draft(
        draft.title,
        draft.package.channel_variants.telegram,
        draft.source_url,
    )
    await message.answer("<b>Telegram variant</b>\n" + telegram_preview["html"])
    await message.answer(
        "<b>Brief variant</b>\n" + html.escape(draft.package.channel_variants.brief)
    )

    if draft.package.caveats:
        caveats = "\n".join(f"• {html.escape(item)}" for item in draft.package.caveats[:5])
        await message.answer("<b>AI caveats</b>\n" + caveats)

    await message.answer(
        f"Saved as <code>{draft.output_id}</code> with status <b>NEEDS_REVIEW</b>. "
        "No approval or publication action was performed."
    )
