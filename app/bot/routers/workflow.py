import base64
import html
import logging
import uuid

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.ai.tools import format_telegram_draft
from app.config import Settings
from app.services.editorial import (
    ArticleNotFoundError,
    EditorialAlreadyRunningError,
    EditorialGenerationError,
    EditorialService,
)
from app.services.ingestion import IngestionService
from app.services.publishing import (
    PublicationAlreadyAttemptedError,
    PublicationNotAllowedError,
    PublicationService,
)
from app.services.translation import (
    TranslationAlreadyRunningError,
    TranslationGenerationError,
    TranslationService,
)

logger = logging.getLogger(__name__)
router = Router(name="button-workflow")


class CopyEditStates(StatesGroup):
    waiting_for_text = State()


def dashboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📰 Incoming articles", callback_data="wf:menu:incoming"),
                InlineKeyboardButton(text="🧪 RU review", callback_data="wf:menu:review:ru"),
            ],
            [
                InlineKeyboardButton(text="🌐 EN review", callback_data="wf:menu:review:en"),
                InlineKeyboardButton(text="📡 Source health", callback_data="wf:menu:sources"),
            ],
            [InlineKeyboardButton(text="🔄 Scan feeds", callback_data="wf:menu:fetch")],
        ]
    )


def _back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⌂ Control deck", callback_data="wf:menu:home")]
        ]
    )


def editorial_review_keyboard(article_id: uuid.UUID) -> InlineKeyboardMarkup:
    key = str(article_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✍️ Edit copy", callback_data=f"wf:edit:ru:{key}"),
                InlineKeyboardButton(text="✅ Approve", callback_data=f"wf:approve:ru:{key}"),
            ],
            [
                InlineKeyboardButton(text="🗑 Reject", callback_data=f"wf:reject:ru:{key}"),
                InlineKeyboardButton(text="🔁 Regenerate", callback_data=f"wf:regen:ru:{key}"),
            ],
            [InlineKeyboardButton(text="📜 Audit log", callback_data=f"wf:history:{key}")],
            [InlineKeyboardButton(text="⌂ Control deck", callback_data="wf:menu:home")],
        ]
    )


def translation_review_keyboard(article_id: uuid.UUID) -> InlineKeyboardMarkup:
    key = str(article_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✍️ Edit English", callback_data=f"wf:edit:en:{key}"),
                InlineKeyboardButton(text="✅ Approve EN", callback_data=f"wf:approve:en:{key}"),
            ],
            [
                InlineKeyboardButton(text="🗑 Reject EN", callback_data=f"wf:reject:en:{key}"),
                InlineKeyboardButton(text="🔁 Re-translate", callback_data=f"wf:regen:en:{key}"),
            ],
            [InlineKeyboardButton(text="📜 Audit log", callback_data=f"wf:history:{key}")],
            [InlineKeyboardButton(text="⌂ Control deck", callback_data="wf:menu:home")],
        ]
    )


def _incoming_keyboard(article_id: uuid.UUID) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🧠 Generate AI draft", callback_data=f"wf:draft:{article_id}")],
            [InlineKeyboardButton(text="⌂ Control deck", callback_data="wf:menu:home")],
        ]
    )


def _pagination_keyboard(
    queue: str,
    *,
    language: str | None = None,
    previous_cursor: str | None = None,
    next_cursor: str | None = None,
) -> InlineKeyboardMarkup:
    buttons = []
    for direction, cursor, label in (
        ("previous", previous_cursor, "◀ Previous"),
        ("next", next_cursor, "Next ▶"),
    ):
        if cursor:
            if queue == "incoming":
                callback_data = f"wf:page:incoming:{direction}:{cursor}"
            else:
                callback_data = f"wf:page:review:{language}:{direction}:{cursor}"
            buttons.append(InlineKeyboardButton(text=label, callback_data=callback_data))
    rows = [buttons] if buttons else []
    rows.append([InlineKeyboardButton(text="⌂ Control deck", callback_data="wf:menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_incoming_page(
    message: Message,
    editorial_service: EditorialService,
    *,
    cursor: str | None = None,
    direction: str = "next",
) -> None:
    page = await editorial_service.pending_articles_page(
        limit=10, cursor=cursor, direction=direction
    )
    if not page.items:
        await message.answer("📭 Incoming queue is clear.", reply_markup=_back_keyboard())
        return
    await message.answer("📰 <b>INCOMING INTELLIGENCE // Select a story</b>")
    for article in page.items:
        await message.answer(
            f"<b>{html.escape(article.title)}</b>\n"
            f"Source: {html.escape(article.source_name)}\n<code>{article.id}</code>",
            reply_markup=_incoming_keyboard(article.id),
        )
    await message.answer(
        "Page navigation",
        reply_markup=_pagination_keyboard(
            "incoming",
            previous_cursor=page.previous_cursor,
            next_cursor=page.next_cursor,
        ),
    )


def _queue_open_keyboard(article_id: uuid.UUID, language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔎 Open review",
                    callback_data=f"wf:open:{language}:{article_id}",
                )
            ],
            [InlineKeyboardButton(text="⌂ Control deck", callback_data="wf:menu:home")],
        ]
    )


def _approved_ru_keyboard(article_id: uuid.UUID) -> InlineKeyboardMarkup:
    key = str(article_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📨 Preview RU channel", callback_data=f"wf:preview:ru:{key}")],
            [
                InlineKeyboardButton(text="🌐 Translate to English", callback_data=f"wf:translate:{key}"),
                InlineKeyboardButton(text="📜 Audit log", callback_data=f"wf:history:{key}"),
            ],
            [InlineKeyboardButton(text="⌂ Control deck", callback_data="wf:menu:home")],
        ]
    )


def _approved_en_keyboard(article_id: uuid.UUID) -> InlineKeyboardMarkup:
    key = str(article_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📨 Preview EN channel", callback_data=f"wf:preview:en:{key}"),
                InlineKeyboardButton(text="📜 Audit log", callback_data=f"wf:history:{key}"),
            ],
            [InlineKeyboardButton(text="⌂ Control deck", callback_data="wf:menu:home")],
        ]
    )


def _uuid_token(value: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(value.bytes).decode("ascii").rstrip("=")


def _uuid_from_token(value: str) -> uuid.UUID | None:
    try:
        padded = value + "=" * (-len(value) % 4)
        return uuid.UUID(bytes=base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError):
        return None


def _parse_uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID((value or "").strip())
    except (ValueError, AttributeError):
        return None


def _is_admin(message: Message, settings: Settings) -> bool:
    return message.from_user is not None and message.from_user.id in settings.admin_id_set


def _is_admin_callback(callback: CallbackQuery, settings: Settings) -> bool:
    return callback.from_user.id in settings.admin_id_set


async def _send_editorial_review(message: Message, item) -> None:
    checks = item.validation.get("checks", [])
    failed = [
        check for check in checks
        if isinstance(check, dict) and not check.get("passed", False)
    ]
    blocking = [check for check in failed if check.get("severity", "error") != "warning"]
    await message.answer(
        "🧪 <b>RUSSIAN EDITORIAL REVIEW</b>\n"
        f"<b>{html.escape(item.title)}</b>\n"
        f"Source: {html.escape(item.source_name)}\n"
        f"Article: <code>{item.article_id}</code>\n"
        f"Validation: {'🚫 BLOCKING CHECKS FAILED' if blocking else '✅ no blocking errors'}"
    )
    rendered = await format_telegram_draft(
        item.title, item.package.channel_variants.telegram, item.source_url
    )
    await message.answer("<b>Telegram preview</b>\n" + rendered["html"])
    await message.answer("<b>Brief variant</b>\n" + html.escape(item.package.channel_variants.brief))
    if failed:
        lines = ["<b>Validation notes</b>"]
        for check in failed[:8]:
            lines.append(
                f"• {html.escape(str(check.get('name', 'check')))}: "
                f"{html.escape(str(check.get('details', 'Needs review')))}"
            )
        await message.answer("\n".join(lines))
    if item.package.caveats:
        await message.answer(
            "<b>⚠️ AI caveats</b>\n"
            + "\n".join(f"• {html.escape(value)}" for value in item.package.caveats[:5])
        )
    await message.answer(
        "Choose an editorial action. Publishing unlocks only after approval.",
        reply_markup=editorial_review_keyboard(item.article_id),
    )


async def _send_translation_review(message: Message, item) -> None:
    checks = item.validation.get("checks", [])
    failed = [
        check for check in checks
        if isinstance(check, dict) and not check.get("passed", False)
    ]
    blocking = [check for check in failed if check.get("severity", "error") != "warning"]
    await message.answer(
        "🌐 <b>ENGLISH TRANSLATION REVIEW</b>\n"
        f"<b>{html.escape(item.package.title)}</b>\n"
        f"Russian title: {html.escape(item.source_title)}\n"
        f"Source: {html.escape(item.source_name)}\n"
        f"Article: <code>{item.article_id}</code>\n"
        f"Validation: {'🚫 BLOCKING CHECKS FAILED' if blocking else '✅ no blocking errors'}"
    )
    rendered = await format_telegram_draft(
        item.package.title, item.package.channel_variants.telegram, item.source_url
    )
    await message.answer("<b>English Telegram preview</b>\n" + rendered["html"])
    await message.answer(
        "<b>English brief</b>\n" + html.escape(item.package.channel_variants.brief)
    )
    if failed:
        lines = ["<b>Translation validation notes</b>"]
        for check in failed[:8]:
            lines.append(
                f"• {html.escape(str(check.get('name', 'check')))}: "
                f"{html.escape(str(check.get('details', 'Needs review')))}"
            )
        await message.answer("\n".join(lines))
    if item.package.caveats:
        await message.answer(
            "<b>⚠️ Translation caveats</b>\n"
            + "\n".join(f"• {html.escape(value)}" for value in item.package.caveats[:5])
        )
    await message.answer(
        "English approval is independent from Russian approval.",
        reply_markup=translation_review_keyboard(item.article_id),
    )


async def _send_approved_ru(message: Message, item) -> None:
    rendered = await format_telegram_draft(
        item.title, item.package.channel_variants.telegram, item.source_url
    )
    await message.answer(
        "✅ <b>RUSSIAN PACKAGE APPROVED</b>\n"
        f"<b>{html.escape(item.title)}</b>\n"
        f"Article: <code>{item.article_id}</code>\n"
        "The approved package has not been published."
    )
    await message.answer(
        "<b>Approved RU Telegram copy</b>\n" + rendered["html"],
        reply_markup=_approved_ru_keyboard(item.article_id),
    )


async def _send_approved_en(message: Message, item) -> None:
    rendered = await format_telegram_draft(
        item.package.title, item.package.channel_variants.telegram, item.source_url
    )
    await message.answer(
        "✅ <b>ENGLISH PACKAGE APPROVED</b>\n"
        f"<b>{html.escape(item.package.title)}</b>\n"
        f"Article: <code>{item.article_id}</code>\n"
        "English approval is independent. This version has not been published."
    )
    await message.answer(
        "<b>Approved EN Telegram copy</b>\n" + rendered["html"],
        reply_markup=_approved_en_keyboard(item.article_id),
    )


async def _send_history(message: Message, article_id: uuid.UUID, editorial_service: EditorialService) -> None:
    history = await editorial_service.action_history(article_id, limit=20)
    if not history:
        await message.answer("📜 No editorial actions recorded for this article.")
        return
    lines = [f"📜 <b>AUDIT LOG</b> — <code>{article_id}</code>"]
    for entry in history:
        timestamp = (
            entry.created_at.strftime("%Y-%m-%d %H:%M UTC")
            if entry.created_at is not None else "time unavailable"
        )
        actor = str(entry.actor_telegram_id) if entry.actor_telegram_id is not None else "system"
        detail = ""
        if entry.details.get("reason"):
            detail = f" — {html.escape(str(entry.details['reason'])[:180])}"
        elif entry.details.get("channel_id"):
            detail = f" — channel {html.escape(str(entry.details['channel_id']))}"
        lines.append(
            f"\n<b>{html.escape(entry.action)}</b> · {timestamp} · actor {actor}{detail}"
        )
    await message.answer("\n".join(lines), reply_markup=_back_keyboard())


async def _send_publish_preview(
    message: Message,
    article_id: uuid.UUID,
    language: str,
    settings: Settings,
    publication_service: PublicationService,
) -> None:
    try:
        channel_id = (settings.publish_channel_for(language) or "").strip()
    except ValueError as exc:
        await message.answer(html.escape(str(exc)))
        return
    if not channel_id:
        variable = "PUBLISH_CHANNEL_ID_EN" if language == "en" else "PUBLISH_CHANNEL_ID"
        await message.answer(
            f"⚙️ Configure <code>{variable}</code> and add the bot to that channel first."
        )
        return
    try:
        payload = await publication_service.get_publishable(article_id, language=language)
    except (ArticleNotFoundError, PublicationNotAllowedError) as exc:
        await message.answer(html.escape(str(exc)))
        return
    rendered = await format_telegram_draft(
        payload.title, payload.telegram_text, payload.source_url
    )
    plain_text = f"{payload.title}\n{payload.telegram_text}"
    length = len(plain_text.encode("utf-16-le")) // 2
    if length > 4096:
        await message.answer(
            f"🚫 Publishing blocked: {length} UTF-16 units exceeds Telegram's 4096-unit limit."
        )
        return
    await message.answer(
        f"🛰️ <b>FINAL {language.upper()} CHANNEL PREVIEW</b>\n"
        f"Destination: <code>{html.escape(channel_id)}</code>\n"
        f"Article: <code>{article_id}</code>\n"
        "Inspect the exact copy below, then confirm to send."
    )
    callback_data = (
        f"wf:confirm:{language}:{_uuid_token(article_id)}:{_uuid_token(payload.output_id)}"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🚀 Confirm {language.upper()} publish", callback_data=callback_data)],
            [InlineKeyboardButton(text="↩ Cancel", callback_data="wf:menu:home")],
        ]
    )
    await message.answer(rendered["html"], reply_markup=keyboard)


async def _publish_now(
    message: Message,
    article_id: uuid.UUID,
    language: str,
    expected_output_id: uuid.UUID,
    settings: Settings,
    publication_service: PublicationService,
    actor_id: int,
) -> bool:
    try:
        channel_id = (settings.publish_channel_for(language) or "").strip()
    except ValueError as exc:
        await message.answer(html.escape(str(exc)))
        return False
    if not channel_id:
        variable = "PUBLISH_CHANNEL_ID_EN" if language == "en" else "PUBLISH_CHANNEL_ID"
        await message.answer(f"⚙️ Configure <code>{variable}</code> first.")
        return False
    try:
        payload = await publication_service.get_publishable(article_id, language=language)
        if payload.output_id != expected_output_id:
            await message.answer(
                "⚠️ The approved output changed after preview. Open a fresh channel preview before sending."
            )
            return False
        rendered = await format_telegram_draft(
            payload.title, payload.telegram_text, payload.source_url
        )
        plain_text = f"{payload.title}\n{payload.telegram_text}"
        length = len(plain_text.encode("utf-16-le")) // 2
        if length > 4096:
            await message.answer(f"🚫 Publishing blocked: {length} UTF-16 units exceeds the limit.")
            return False
        attempt = await publication_service.reserve_publication(
            article_id,
            channel_id,
            actor_telegram_id=actor_id,
            expected_output_id=expected_output_id,
            language=language,
        )
    except PublicationAlreadyAttemptedError as exc:
        await message.answer(
            f"🛡️ No resend attempted. Existing {language.upper()} publication state: "
            f"<b>{html.escape(exc.status)}</b>. Check the channel and audit log."
        )
        return False
    except (ArticleNotFoundError, PublicationNotAllowedError) as exc:
        await message.answer(html.escape(str(exc)))
        return False
    except Exception:
        logger.exception("Could not reserve %s publication for article %s", language, article_id)
        await message.answer("Could not reserve publication. No Telegram send was attempted.")
        return False

    try:
        sent = await message.bot.send_message(
            chat_id=channel_id,
            text=rendered["html"],
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        logger.exception("Telegram send outcome is uncertain for article %s", article_id)
        try:
            await publication_service.mark_unknown(
                attempt.publication_id, actor_telegram_id=actor_id, error_type=type(exc).__name__
            )
        except Exception:
            logger.exception("Could not persist UNKNOWN publication status")
        await message.answer(
            f"⚠️ Telegram did not confirm the {language.upper()} send. It is marked UNKNOWN "
            "and will not be retried automatically. Check the channel manually."
        )
        return False
    try:
        await publication_service.mark_published(
            attempt.publication_id, message_id=sent.message_id, actor_telegram_id=actor_id
        )
    except Exception:
        logger.exception("Message was sent but publication finalization failed")
        await message.answer(
            f"⚠️ Telegram accepted message {sent.message_id}, but database finalization failed. "
            "Check the channel and database before proceeding."
        )
        return False
    await message.answer(
        f"🚀 <b>{language.upper()} ARTICLE PUBLISHED</b>\n"
        f"Destination: <code>{html.escape(channel_id)}</code>\n"
        f"Telegram message ID: <code>{sent.message_id}</code>",
        reply_markup=dashboard_keyboard(),
    )
    return True


async def _send_queue(
    message: Message,
    language: str,
    editorial_service: EditorialService,
    translation_service: TranslationService,
    *,
    cursor: str | None = None,
    direction: str = "next",
) -> None:
    if language == "ru":
        page = await editorial_service.review_queue_page(
            limit=10, cursor=cursor, direction=direction
        )
        if not page.items:
            await message.answer("📭 Russian review queue is clear.", reply_markup=_back_keyboard())
            return
        await message.answer("🧪 <b>RUSSIAN REVIEW QUEUE</b>")
        for item in page.items:
            await message.answer(
                f"<b>{html.escape(item.title)}</b>\n"
                f"Source: {html.escape(item.source_name)}\n<code>{item.article_id}</code>",
                reply_markup=_queue_open_keyboard(item.article_id, "ru"),
            )
    else:
        page = await translation_service.translation_queue_page(
            language="en", limit=10, cursor=cursor, direction=direction
        )
        if not page.items:
            await message.answer("📭 English review queue is clear.", reply_markup=_back_keyboard())
            return
        await message.answer("🌐 <b>ENGLISH TRANSLATION QUEUE</b>")
        for item in page.items:
            await message.answer(
                f"<b>{html.escape(item.package.title)}</b>\n"
                f"RU: {html.escape(item.source_title)}\n"
                f"Source: {html.escape(item.source_name)}\n<code>{item.article_id}</code>",
                reply_markup=_queue_open_keyboard(item.article_id, "en"),
            )
    await message.answer(
        "Page navigation",
        reply_markup=_pagination_keyboard(
            "review",
            language=language,
            previous_cursor=page.previous_cursor,
            next_cursor=page.next_cursor,
        ),
    )


@router.callback_query(F.data.startswith("wf:"))
async def workflow_callback(
    callback: CallbackQuery,
    settings: Settings,
    editorial_service: EditorialService,
    translation_service: TranslationService,
    publication_service: PublicationService,
    ingestion_service: IngestionService,
    state: FSMContext,
) -> None:
    if not _is_admin_callback(callback, settings):
        await callback.answer("Administrator access required.", show_alert=True)
        return
    if not callback.data or not isinstance(callback.message, Message):
        await callback.answer("This workflow message is no longer available.", show_alert=True)
        return
    target = callback.message
    parts = callback.data.split(":")
    actor_id = callback.from_user.id

    if len(parts) == 5 and parts[:3] == ["wf", "page", "incoming"]:
        direction, cursor = parts[3], parts[4]
        if direction not in {"next", "previous"}:
            await callback.answer("Invalid page navigation.", show_alert=True)
            return
        await callback.answer("Loading incoming stories…")
        try:
            await _send_incoming_page(
                target, editorial_service, cursor=cursor, direction=direction
            )
        except ValueError:
            await target.answer("That page cursor is no longer valid. Reopen the queue.")
        except Exception:
            logger.exception("Could not load incoming article page")
            await target.answer("Could not load incoming stories. Check application logs.")
        return
    if len(parts) == 6 and parts[:3] == ["wf", "page", "review"]:
        language, direction, cursor = parts[3], parts[4], parts[5]
        if language not in {"ru", "en"} or direction not in {"next", "previous"}:
            await callback.answer("Invalid page navigation.", show_alert=True)
            return
        await callback.answer("Loading review queue…")
        try:
            await _send_queue(
                target,
                language,
                editorial_service,
                translation_service,
                cursor=cursor,
                direction=direction,
            )
        except ValueError:
            await target.answer("That page cursor is no longer valid. Reopen the queue.")
        except Exception:
            logger.exception("Could not load review queue page")
            await target.answer("Could not load this review queue. Check application logs.")
        return

    if parts == ["wf", "menu", "home"]:
        await callback.answer()
        await target.answer(
            "🛰️ <b>NEWS OPS // CONTROL DECK</b>\nSelect a workflow stage.",
            reply_markup=dashboard_keyboard(),
        )
        return
    if parts == ["wf", "menu", "incoming"]:
        await callback.answer("Loading incoming stories…")
        try:
            await _send_incoming_page(target, editorial_service)
        except Exception:
            logger.exception("Could not load incoming article queue")
            await target.answer("Could not load incoming stories. Check application logs.")
        return
    if parts in (["wf", "menu", "review", "ru"], ["wf", "menu", "review", "en"]):
        await callback.answer("Loading review queue…")
        try:
            await _send_queue(target, parts[-1], editorial_service, translation_service)
        except Exception:
            logger.exception("Could not load %s moderation queue", parts[-1])
            await target.answer("Could not load this review queue. Check application logs.")
        return
    if parts == ["wf", "menu", "sources"]:
        await callback.answer("Loading source telemetry…")
        try:
            sources = await ingestion_service.source_health()
        except Exception:
            logger.exception("Could not load source health")
            await target.answer("Could not read source telemetry. Check application logs.")
            return
        if not sources:
            await target.answer("📡 No source health records yet.", reply_markup=_back_keyboard())
            return
        lines = ["📡 <b>SOURCE TELEMETRY</b>"]
        for source in sources:
            attempts = source.last_attempt_at.strftime("%Y-%m-%d %H:%M UTC") if source.last_attempt_at else "never"
            lines.append(
                f"\n<b>{html.escape(source.name)}</b> — {html.escape(source.status or 'NOT RUN')}"
                f"\nLast attempt: {attempts}; fetched: {source.last_fetched_count}; "
                f"consecutive failures: {source.consecutive_failures}"
            )
            if source.last_error:
                lines.append(f"Note: {html.escape(source.last_error[:240])}")
        await target.answer("\n".join(lines), reply_markup=_back_keyboard())
        return
    if parts == ["wf", "menu", "fetch"]:
        await callback.answer("Scanning configured sources…")
        try:
            result = await ingestion_service.ingest(limit=settings.source_fetch_limit)
        except Exception:
            logger.exception("Manual feed scan failed from control deck")
            await target.answer("Feed scan failed. The error was logged.")
            return
        await target.answer(
            "🔄 <b>FEED SCAN COMPLETE</b>\n"
            f"Sources checked: <b>{result.sources_checked}</b>\n"
            f"New stories: <b>{result.created}</b>\n"
            f"Duplicate candidates: <b>{result.duplicates}</b>\n"
            f"Source failures: <b>{result.failures}</b>",
            reply_markup=dashboard_keyboard(),
        )
        return

    if len(parts) == 3 and parts[1] == "draft":
        article_id = _parse_uuid(parts[2])
        if article_id is None:
            await callback.answer("Invalid article ID.", show_alert=True)
            return
        await callback.answer("Generating editorial draft…")
        await target.answer("🧠 AI editor is preparing a structured draft. Human review is required…")
        try:
            draft = await editorial_service.draft_article(article_id, actor_telegram_id=actor_id)
            item = await editorial_service.get_review_item(article_id)
        except (
            ArticleNotFoundError,
            EditorialAlreadyRunningError,
            EditorialGenerationError,
            ValueError,
        ) as exc:
            await target.answer(html.escape(str(exc)), reply_markup=_back_keyboard())
            return
        except Exception:
            logger.exception("AI draft button failed for article %s", article_id)
            await target.answer("Draft generation failed. Check application logs.")
            return
        await target.answer(
            f"⚡ Draft created by {html.escape(draft.provider)} / {html.escape(draft.model)}. "
            f"Confidence estimate: {draft.package.confidence:.2f}."
        )
        await _send_editorial_review(target, item)
        return

    if len(parts) == 4 and parts[1] == "open" and parts[2] in {"ru", "en"}:
        article_id = _parse_uuid(parts[3])
        if article_id is None:
            await callback.answer("Invalid article ID.", show_alert=True)
            return
        await callback.answer("Opening review…")
        try:
            if parts[2] == "ru":
                await _send_editorial_review(target, await editorial_service.get_review_item(article_id))
            else:
                await _send_translation_review(target, await translation_service.get_review_item(article_id))
        except (ArticleNotFoundError, ValueError) as exc:
            await target.answer(html.escape(str(exc)))
        except Exception:
            logger.exception("Could not open review card for %s", article_id)
            await target.answer("Could not open review. Check application logs.")
        return

    if len(parts) == 4 and parts[1] == "edit" and parts[2] in {"ru", "en"}:
        article_id = _parse_uuid(parts[3])
        if article_id is None:
            await callback.answer("Invalid article ID.", show_alert=True)
            return
        await state.update_data(article_id=str(article_id), language=parts[2])
        await state.set_state(CopyEditStates.waiting_for_text)
        await callback.answer("Edit mode ready.")
        language_name = "Russian" if parts[2] == "ru" else "English"
        await target.answer(
            f"✍️ <b>EDIT {language_name.upper()} TELEGRAM COPY</b>\n"
            "Send the complete replacement text as your next message. "
            "It is treated as plain text and added to the audit log.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="↩ Cancel edit", callback_data="wf:cancel_edit")]
                ]
            ),
        )
        return

    if len(parts) == 4 and parts[1] in {"approve", "reject", "regen"} and parts[2] in {"ru", "en"}:
        action, language = parts[1], parts[2]
        article_id = _parse_uuid(parts[3])
        if article_id is None:
            await callback.answer("Invalid article ID.", show_alert=True)
            return
        await callback.answer(
            {"approve": "Recording approval…", "reject": "Recording rejection…", "regen": "Regeneration started…"}[action]
        )
        try:
            if action == "approve" and language == "ru":
                item = await editorial_service.approve_article(article_id, actor_id)
                await target.edit_reply_markup(reply_markup=None)
                await _send_approved_ru(target, item)
            elif action == "approve" and language == "en":
                item = await translation_service.approve_translation(article_id, actor_id)
                await target.edit_reply_markup(reply_markup=None)
                await _send_approved_en(target, item)
            elif action == "reject" and language == "ru":
                await editorial_service.reject_article(
                    article_id, actor_telegram_id=actor_id, reason="Rejected from button-driven review"
                )
                await target.edit_reply_markup(reply_markup=None)
                await target.answer("🗑 Russian draft rejected and recorded.", reply_markup=_back_keyboard())
            elif action == "reject" and language == "en":
                await translation_service.reject_translation(
                    article_id, actor_telegram_id=actor_id, reason="Rejected from button-driven English review"
                )
                await target.edit_reply_markup(reply_markup=None)
                await target.answer("🗑 English translation rejected and recorded.", reply_markup=_back_keyboard())
            elif action == "regen" and language == "ru":
                draft = await editorial_service.draft_article(article_id, actor_telegram_id=actor_id)
                item = await editorial_service.get_review_item(article_id)
                await target.answer(
                    f"🔁 New draft generated ({html.escape(draft.provider)} / {html.escape(draft.model)})."
                )
                await _send_editorial_review(target, item)
            else:
                await translation_service.translate_article(
                    article_id, target_language="en", actor_telegram_id=actor_id
                )
                item = await translation_service.get_review_item(article_id)
                await target.answer("🔁 English translation regenerated.")
                await _send_translation_review(target, item)
        except (
            ArticleNotFoundError,
            EditorialAlreadyRunningError,
            EditorialGenerationError,
            TranslationAlreadyRunningError,
            TranslationGenerationError,
            ValueError,
        ) as exc:
            await target.answer(html.escape(str(exc)))
        except Exception:
            logger.exception("Button-driven %s action failed for %s", action, article_id)
            await target.answer("The action failed. Check application logs.")
        return

    if len(parts) == 3 and parts[1] == "translate":
        article_id = _parse_uuid(parts[2])
        if article_id is None:
            await callback.answer("Invalid article ID.", show_alert=True)
            return
        await callback.answer("Creating English translation…")
        try:
            await translation_service.translate_article(
                article_id, target_language="en", actor_telegram_id=actor_id
            )
            item = await translation_service.get_review_item(article_id)
            await _send_translation_review(target, item)
        except (
            ArticleNotFoundError,
            TranslationAlreadyRunningError,
            TranslationGenerationError,
            ValueError,
        ) as exc:
            await target.answer(html.escape(str(exc)))
        except Exception:
            logger.exception("Translation button failed for article %s", article_id)
            await target.answer("Translation failed. Check application logs.")
        return

    if len(parts) == 3 and parts[1] == "history":
        article_id = _parse_uuid(parts[2])
        if article_id is None:
            await callback.answer("Invalid article ID.", show_alert=True)
            return
        await callback.answer("Loading audit history…")
        try:
            await _send_history(target, article_id, editorial_service)
        except ArticleNotFoundError:
            await target.answer("Article was not found.")
        except Exception:
            logger.exception("Could not load audit history for %s", article_id)
            await target.answer("Could not load audit history. Check application logs.")
        return

    if len(parts) == 4 and parts[1] == "preview" and parts[2] in {"ru", "en"}:
        article_id = _parse_uuid(parts[3])
        if article_id is None:
            await callback.answer("Invalid article ID.", show_alert=True)
            return
        await callback.answer("Preparing channel preview…")
        await _send_publish_preview(
            target, article_id, parts[2], settings, publication_service
        )
        return

    if len(parts) == 5 and parts[1] == "confirm" and parts[2] in {"ru", "en"}:
        article_id = _uuid_from_token(parts[3])
        output_id = _uuid_from_token(parts[4])
        if article_id is None or output_id is None:
            await callback.answer("Invalid publish confirmation.", show_alert=True)
            return
        await callback.answer("Verifying approval and sending…")
        published = await _publish_now(
            target, article_id, parts[2], output_id, settings, publication_service, actor_id
        )
        if published:
            await target.edit_reply_markup(reply_markup=None)
        return

    if parts == ["wf", "cancel_edit"]:
        await state.clear()
        await callback.answer("Edit cancelled.")
        await target.answer("↩️ Edit cancelled.", reply_markup=dashboard_keyboard())
        return

    await callback.answer("Unknown workflow action.", show_alert=True)


@router.message(CopyEditStates.waiting_for_text)
async def receive_copy_edit(
    message: Message,
    state: FSMContext,
    settings: Settings,
    editorial_service: EditorialService,
    translation_service: TranslationService,
) -> None:
    if not _is_admin(message, settings):
        await state.clear()
        await message.answer("Administrator access required.")
        return
    if message.text is None:
        await message.answer("Send the replacement copy as a text message.")
        return
    if message.text.strip().casefold() in {"/cancel", "cancel"}:
        await state.clear()
        await message.answer("↩️ Edit cancelled.", reply_markup=dashboard_keyboard())
        return
    data = await state.get_data()
    article_id = _parse_uuid(data.get("article_id"))
    language = str(data.get("language", "ru"))
    if article_id is None or language not in {"ru", "en"}:
        await state.clear()
        await message.answer("Edit session expired. Open the review card again.")
        return
    try:
        if language == "ru":
            item = await editorial_service.edit_telegram_variant(
                article_id, message.text, actor_telegram_id=message.from_user.id
            )
            await state.clear()
            await message.answer("📝 Russian copy updated and audited.")
            await _send_editorial_review(message, item)
        else:
            item = await translation_service.edit_telegram_variant(
                article_id, message.text, actor_telegram_id=message.from_user.id
            )
            await state.clear()
            await message.answer("📝 English copy updated and audited.")
            await _send_translation_review(message, item)
    except (ArticleNotFoundError, ValueError) as exc:
        await message.answer(html.escape(str(exc)) + "\nSend a corrected version or press Cancel edit.")
    except Exception:
        logger.exception("Button-driven copy edit failed for article %s", article_id)
        await state.clear()
        await message.answer("Could not save the edit. Check application logs.")
