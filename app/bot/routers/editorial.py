import html
import logging
import uuid

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
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
    EditorialReviewItem,
    EditorialService,
)
from app.services.publishing import (
    PublicationAlreadyAttemptedError,
    PublicationNotAllowedError,
    PublicationService,
)
from app.services.translation import (
    TranslationAlreadyRunningError,
    TranslationGenerationError,
    TranslationReviewItem,
    TranslationService,
)

logger = logging.getLogger(__name__)
router = Router(name="editorial")


def _is_admin(message: Message, settings: Settings) -> bool:
    return message.from_user is not None and message.from_user.id in settings.admin_id_set


def _is_admin_callback(callback: CallbackQuery, settings: Settings) -> bool:
    return callback.from_user.id in settings.admin_id_set


def _review_keyboard(article_id: uuid.UUID) -> InlineKeyboardMarkup:
    article_key = str(article_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Edit text", callback_data=f"ed:edit:{article_key}"),
                InlineKeyboardButton(text="Approve", callback_data=f"ed:approve:{article_key}"),
            ],
            [
                InlineKeyboardButton(text="Reject", callback_data=f"ed:reject:{article_key}"),
                InlineKeyboardButton(text="Regenerate", callback_data=f"ed:regen:{article_key}"),
            ],
        ]
    )


async def _send_review(
    message: Message,
    item: EditorialReviewItem,
    *,
    include_actions: bool = True,
) -> None:
    check_items = item.validation.get("checks", [])
    failed_checks = [
        check
        for check in check_items
        if isinstance(check, dict) and not check.get("passed", False)
    ]
    blocking = [
        check for check in failed_checks if check.get("severity", "error") != "warning"
    ]
    summary = (
        f"<b>Review draft — {html.escape(item.title)}</b>\n"
        f"Source: {html.escape(item.source_name)}\n"
        f"Article: <code>{item.article_id}</code>\n"
        f"Draft: <code>{item.output_id}</code>\n"
        f"Validation: {'BLOCKING CHECKS FAILED' if blocking else 'no blocking errors'}"
    )
    await message.answer(summary)

    telegram_preview = await format_telegram_draft(
        item.title,
        item.package.channel_variants.telegram,
        item.source_url,
    )
    await message.answer("<b>Telegram preview</b>\n" + telegram_preview["html"])
    await message.answer(
        "<b>Brief variant</b>\n" + html.escape(item.package.channel_variants.brief)
    )
    if failed_checks:
        lines = ["<b>Validation warnings</b>"]
        for check in failed_checks[:8]:
            lines.append(
                f"• {html.escape(str(check.get('name', 'check')))}: "
                f"{html.escape(str(check.get('details', 'Needs review')))}"
            )
        await message.answer("\n".join(lines))
    if item.package.caveats:
        caveats = "\n".join(
            f"• {html.escape(caveat)}" for caveat in item.package.caveats[:5]
        )
        await message.answer("<b>AI caveats</b>\n" + caveats)
    if include_actions:
        await message.answer(
            "Choose a moderation action. Publishing is a separate, explicit /publish command.",
            reply_markup=_review_keyboard(item.article_id),
        )



def _translation_review_keyboard(article_id: uuid.UUID) -> InlineKeyboardMarkup:
    article_key = str(article_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Edit English", callback_data=f"tr:edit:{article_key}"),
                InlineKeyboardButton(text="Approve English", callback_data=f"tr:approve:{article_key}"),
            ],
            [
                InlineKeyboardButton(text="Reject English", callback_data=f"tr:reject:{article_key}"),
            ],
        ]
    )


async def _send_translation_review(
    message: Message,
    item: TranslationReviewItem,
    *,
    include_actions: bool = True,
) -> None:
    checks = item.validation.get("checks", [])
    failed = [
        check for check in checks
        if isinstance(check, dict) and not check.get("passed", False)
    ]
    blocking = [check for check in failed if check.get("severity", "error") != "warning"]
    await message.answer(
        "<b>English translation — HUMAN REVIEW REQUIRED</b>\n"
        f"<b>{html.escape(item.package.title)}</b>\n"
        f"Russian title: {html.escape(item.source_title)}\n"
        f"Source: {html.escape(item.source_name)}\n"
        f"Article: <code>{item.article_id}</code>\n"
        f"Translation: <code>{item.output_id}</code>\n"
        f"Validation: {'BLOCKING CHECKS FAILED' if blocking else 'no blocking errors'}"
    )
    rendered = await format_telegram_draft(
        item.package.title,
        item.package.channel_variants.telegram,
        item.source_url,
    )
    await message.answer("<b>English Telegram preview</b>\n" + rendered["html"])
    await message.answer(
        "<b>English brief</b>\n" + html.escape(item.package.channel_variants.brief)
    )
    if failed:
        lines = ["<b>Translation validation warnings</b>"]
        for check in failed[:8]:
            lines.append(
                f"• {html.escape(str(check.get('name', 'check')))}: "
                f"{html.escape(str(check.get('details', 'Needs review')))}"
            )
        await message.answer("\n".join(lines))
    if item.package.caveats:
        caveats = "\n".join(
            f"• {html.escape(value)}" for value in item.package.caveats[:5]
        )
        await message.answer("<b>Translation caveats</b>\n" + caveats)
    if include_actions:
        await message.answer(
            "English approval is independent from the Russian version. "
            "Publishing is a separate /publish ARTICLE_UUID en action.",
            reply_markup=_translation_review_keyboard(item.article_id),
        )


def _parse_article_id(raw_value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID((raw_value or "").strip())
    except (ValueError, AttributeError):
        return None


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

    article_id = _parse_article_id(command.args)
    if article_id is None:
        await message.answer("Usage: <code>/draft ARTICLE_UUID</code>. Get IDs with /drafts.")
        return

    await message.answer("Preparing an AI editorial draft. It will require human review…")
    try:
        draft = await editorial_service.draft_article(
            article_id,
            actor_telegram_id=message.from_user.id if message.from_user else None,
        )
        item = await editorial_service.get_review_item(article_id)
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

    await message.answer(
        f"Draft created by {html.escape(draft.provider)} / {html.escape(draft.model)}. "
        f"Confidence estimate: {draft.package.confidence:.2f}."
    )
    await _send_review(message, item)


@router.message(Command("translate"))
async def translate_command(
    message: Message,
    command: CommandObject,
    settings: Settings,
    translation_service: TranslationService,
) -> None:
    if not _is_admin(message, settings):
        await message.answer("This command is available to configured administrators only.")
        return
    args = (command.args or "").strip().split()
    article_id = _parse_article_id(args[0] if args else None)
    language = args[1].casefold() if len(args) > 1 else "en"
    if article_id is None or len(args) > 2 or language != "en":
        await message.answer("Usage: <code>/translate ARTICLE_UUID en</code>.")
        return

    await message.answer(
        "Translating the approved Russian editorial package into English. "
        "The English version will require separate human approval…"
    )
    try:
        await translation_service.translate_article(
            article_id,
            target_language=language,
            actor_telegram_id=message.from_user.id if message.from_user else None,
        )
        item = await translation_service.get_review_item(article_id)
    except (ArticleNotFoundError, TranslationAlreadyRunningError, TranslationGenerationError, ValueError) as exc:
        await message.answer(html.escape(str(exc)))
        return
    except Exception:
        logger.exception("Could not translate article %s", article_id)
        await message.answer("Translation failed. Check application logs.")
        return
    await _send_translation_review(message, item)


@router.message(Command("review"))
async def review_command(
    message: Message,
    command: CommandObject,
    settings: Settings,
    editorial_service: EditorialService,
    translation_service: TranslationService,
) -> None:
    if not _is_admin(message, settings):
        await message.answer("This command is available to configured administrators only.")
        return

    args = (command.args or "").strip().split()
    language = "ru"
    article_id = None
    if len(args) == 1 and args[0].casefold() in {"ru", "en"}:
        language = args[0].casefold()
    elif len(args) == 1:
        article_id = _parse_article_id(args[0])
    elif len(args) == 2:
        article_id = _parse_article_id(args[0])
        language = args[1].casefold()
    elif args:
        await message.answer(
            "Usage: <code>/review [ARTICLE_UUID] [ru|en]</code>."
        )
        return

    if language not in {"ru", "en"} or (
        args and article_id is None and not (len(args) == 1 and args[0].casefold() in {"ru", "en"})
    ):
        await message.answer("Use /review [ARTICLE_UUID] [ru|en].")
        return

    try:
        if article_id is not None:
            if language == "en":
                item = await translation_service.get_review_item(article_id)
                await _send_translation_review(message, item)
            else:
                item = await editorial_service.get_review_item(article_id)
                await _send_review(message, item)
            return

        if language == "en":
            queue = await translation_service.translation_queue(language="en", limit=10)
            if not queue:
                await message.answer("No English translations are waiting for moderation.")
                return
            lines = ["<b>English translations awaiting moderation</b>"]
            for item in queue:
                lines.append(
                    f"\n<b>{html.escape(item.package.title)}</b>"
                    f"\nRussian: {html.escape(item.source_title)}"
                    f"\nSource: {html.escape(item.source_name)}"
                    f"\n<code>{item.article_id}</code>"
                    f"\nOpen: <code>/review {item.article_id} en</code>"
                )
        else:
            queue = await editorial_service.review_queue(limit=10)
            if not queue:
                await message.answer("No Russian editorial drafts are waiting for moderation.")
                return
            lines = ["<b>Russian editorial drafts awaiting moderation</b>"]
            for item in queue:
                lines.append(
                    f"\n<b>{html.escape(item.title)}</b>"
                    f"\nSource: {html.escape(item.source_name)}"
                    f"\n<code>{item.article_id}</code>"
                    f"\nOpen: <code>/review {item.article_id}</code>"
                )
        await message.answer("\n".join(lines))
    except ArticleNotFoundError:
        await message.answer("Article was not found.")
    except ValueError as exc:
        await message.answer(html.escape(str(exc)))
    except Exception:
        logger.exception("Could not load %s moderation queue", language)
        await message.answer("Could not load the moderation queue. Check application logs.")


@router.message(Command("edit"))
async def edit_command(
    message: Message,
    command: CommandObject,
    settings: Settings,
    editorial_service: EditorialService,
    translation_service: TranslationService,
) -> None:
    if not _is_admin(message, settings):
        await message.answer("This command is available to configured administrators only.")
        return

    args = (command.args or "").strip().split(maxsplit=2)
    article_id = _parse_article_id(args[0] if args else None)
    if article_id is None or len(args) < 2:
        await message.answer(
            "Usage: <code>/edit ARTICLE_UUID [en] new Telegram text</code>. "
            "Replacement text is treated as plain text."
        )
        return
    language = "ru"
    if len(args) == 3 and args[1].casefold() == "en":
        language = "en"
        replacement_text = args[2]
    elif len(args) == 2:
        replacement_text = args[1]
    else:
        await message.answer("Usage: <code>/edit ARTICLE_UUID en new English text</code>.")
        return
    try:
        if language == "en":
            item = await translation_service.edit_telegram_variant(
                article_id,
                replacement_text,
                actor_telegram_id=message.from_user.id if message.from_user else 0,
            )
            await message.answer("English Telegram text updated and audited.")
            await _send_translation_review(message, item)
        else:
            item = await editorial_service.edit_telegram_variant(
                article_id,
                replacement_text,
                actor_telegram_id=message.from_user.id if message.from_user else 0,
            )
            await message.answer("Telegram text updated and the change was added to the audit history.")
            await _send_review(message, item)
    except (ArticleNotFoundError, ValueError) as exc:
        await message.answer(html.escape(str(exc)))
    except Exception:
        logger.exception("Could not edit %s text for article %s", language, article_id)
        await message.answer("Could not save the edit. Check application logs.")


@router.message(Command("regenerate"))
async def regenerate_command(
    message: Message,
    command: CommandObject,
    settings: Settings,
    editorial_service: EditorialService,
) -> None:
    if not _is_admin(message, settings):
        await message.answer("This command is available to configured administrators only.")
        return
    article_id = _parse_article_id(command.args)
    if article_id is None:
        await message.answer("Usage: <code>/regenerate ARTICLE_UUID</code>.")
        return
    await message.answer("Regenerating the AI draft. The current draft remains active until this finishes…")
    try:
        draft = await editorial_service.draft_article(
            article_id,
            actor_telegram_id=message.from_user.id if message.from_user else None,
        )
        item = await editorial_service.get_review_item(article_id)
    except (ArticleNotFoundError, EditorialAlreadyRunningError, EditorialGenerationError, ValueError) as exc:
        await message.answer(html.escape(str(exc)))
        return
    except Exception:
        logger.exception("Could not regenerate article %s", article_id)
        await message.answer("Regeneration failed. Check application logs.")
        return
    await message.answer(
        f"New draft created ({html.escape(draft.provider)} / {html.escape(draft.model)}). "
        "The previous review draft was marked SUPERSEDED."
    )
    await _send_review(message, item)


@router.message(Command("approve"))
async def approve_command(
    message: Message,
    command: CommandObject,
    settings: Settings,
    editorial_service: EditorialService,
    translation_service: TranslationService,
) -> None:
    if not _is_admin(message, settings):
        await message.answer("This command is available to configured administrators only.")
        return
    args = (command.args or "").strip().split()
    article_id = _parse_article_id(args[0] if args else None)
    language = args[1].casefold() if len(args) > 1 else "ru"
    if article_id is None or len(args) > 2 or language not in {"ru", "en"}:
        await message.answer("Usage: <code>/approve ARTICLE_UUID [ru|en]</code>.")
        return
    try:
        if language == "en":
            await translation_service.approve_translation(
                article_id,
                actor_telegram_id=message.from_user.id if message.from_user else 0,
            )
        else:
            await editorial_service.approve_article(
                article_id,
                actor_telegram_id=message.from_user.id if message.from_user else 0,
            )
    except (ArticleNotFoundError, ValueError) as exc:
        await message.answer(html.escape(str(exc)))
        return
    except Exception:
        logger.exception("Could not approve %s version of article %s", language, article_id)
        await message.answer("Approval failed. Check application logs.")
        return
    await message.answer(
        f"Article <code>{article_id}</code> ({language.upper()}) approved. "
        "It has <b>not</b> been published. Use /publish ARTICLE_UUID [ru|en] explicitly."
    )


@router.message(Command("reject"))
async def reject_command(
    message: Message,
    command: CommandObject,
    settings: Settings,
    editorial_service: EditorialService,
    translation_service: TranslationService,
) -> None:
    if not _is_admin(message, settings):
        await message.answer("This command is available to configured administrators only.")
        return
    args = (command.args or "").strip().split(maxsplit=2)
    article_id = _parse_article_id(args[0] if args else None)
    if article_id is None:
        await message.answer("Usage: <code>/reject ARTICLE_UUID [ru|en] [REASON]</code>.")
        return
    language = "ru"
    reason = "Rejected by editor from Telegram"
    if len(args) >= 2:
        if args[1].casefold() in {"ru", "en"}:
            language = args[1].casefold()
            if len(args) == 3:
                reason = args[2]
        else:
            reason = " ".join(args[1:])
    try:
        if language == "en":
            await translation_service.reject_translation(
                article_id,
                actor_telegram_id=message.from_user.id if message.from_user else 0,
                reason=reason,
            )
        else:
            await editorial_service.reject_article(
                article_id,
                actor_telegram_id=message.from_user.id if message.from_user else 0,
                reason=reason,
            )
    except (ArticleNotFoundError, ValueError) as exc:
        await message.answer(html.escape(str(exc)))
        return
    except Exception:
        logger.exception("Could not reject %s version of article %s", language, article_id)
        await message.answer("Rejection failed. Check application logs.")
        return
    await message.answer(
        f"Article <code>{article_id}</code> ({language.upper()}) rejected. The reason was recorded."
    )


@router.message(Command("history"))
async def history_command(
    message: Message,
    command: CommandObject,
    settings: Settings,
    editorial_service: EditorialService,
) -> None:
    if not _is_admin(message, settings):
        await message.answer("This command is available to configured administrators only.")
        return
    article_id = _parse_article_id(command.args)
    if article_id is None:
        await message.answer("Usage: <code>/history ARTICLE_UUID</code>.")
        return
    try:
        history = await editorial_service.action_history(article_id, limit=20)
    except ArticleNotFoundError:
        await message.answer("Article was not found.")
        return
    except Exception:
        logger.exception("Could not load audit history for %s", article_id)
        await message.answer("Could not load the audit history. Check application logs.")
        return
    if not history:
        await message.answer("No editorial actions have been recorded for this article.")
        return
    lines = [f"<b>Editorial audit history</b> — <code>{article_id}</code>"]
    for entry in history:
        timestamp = (
            entry.created_at.strftime("%Y-%m-%d %H:%M UTC")
            if entry.created_at is not None
            else "time unavailable"
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
    await message.answer("\n".join(lines))


@router.message(Command("publish"))
async def publish_command(
    message: Message,
    command: CommandObject,
    settings: Settings,
    publication_service: PublicationService,
) -> None:
    if not _is_admin(message, settings):
        await message.answer("This command is available to configured administrators only.")
        return
    args = (command.args or "").strip().split()
    article_id = _parse_article_id(args[0] if args else None)
    language = args[1].casefold() if len(args) > 1 else "ru"
    if article_id is None or len(args) > 2 or language not in {"ru", "en"}:
        await message.answer("Usage: <code>/publish ARTICLE_UUID [ru|en]</code>.")
        return
    try:
        channel_id = (settings.publish_channel_for(language) or "").strip()
    except ValueError as exc:
        await message.answer(html.escape(str(exc)))
        return
    if not channel_id:
        variable = "PUBLISH_CHANNEL_ID_EN" if language == "en" else "PUBLISH_CHANNEL_ID"
        await message.answer(f"Publishing is disabled: configure {variable} first.")
        return

    try:
        payload = await publication_service.get_publishable(article_id, language=language)
    except (ArticleNotFoundError, PublicationNotAllowedError) as exc:
        await message.answer(html.escape(str(exc)))
        return
    except Exception:
        logger.exception("Could not prepare article %s for %s publication", article_id, language)
        await message.answer("Could not prepare the publication. Check application logs.")
        return

    rendered = await format_telegram_draft(
        payload.title,
        payload.telegram_text,
        payload.source_url,
    )
    plain_text = f"{payload.title}\n{payload.telegram_text}"
    telegram_length = len(plain_text.encode("utf-16-le")) // 2
    if telegram_length > 4096:
        await message.answer(
            f"Publishing blocked: the final message is {telegram_length} UTF-16 units; "
            "Telegram allows at most 4096. Edit and approve a shorter variant."
        )
        return

    actor_id = message.from_user.id if message.from_user else 0
    try:
        attempt = await publication_service.reserve_publication(
            article_id,
            channel_id,
            actor_telegram_id=actor_id,
            expected_output_id=payload.output_id,
            language=language,
        )
    except PublicationAlreadyAttemptedError as exc:
        await message.answer(
            f"{language.upper()} publication is not being sent again. Existing attempt status: "
            f"<b>{html.escape(exc.status)}</b>. Check the destination channel and /history."
        )
        return
    except (ArticleNotFoundError, PublicationNotAllowedError) as exc:
        await message.answer(html.escape(str(exc)))
        return
    except Exception:
        logger.exception("Could not reserve %s publication for article %s", language, article_id)
        await message.answer("Could not reserve the publication. No Telegram send was attempted.")
        return

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
                attempt.publication_id,
                actor_telegram_id=actor_id,
                error_type=type(exc).__name__,
            )
        except Exception:
            logger.exception("Could not persist UNKNOWN publication status")
        await message.answer(
            f"Telegram did not confirm the {language.upper()} send. It is marked UNKNOWN and "
            "will not be retried automatically. Check the channel manually."
        )
        return

    try:
        await publication_service.mark_published(
            attempt.publication_id,
            message_id=sent.message_id,
            actor_telegram_id=actor_id,
        )
    except Exception:
        logger.exception("Message was sent but publication finalization failed")
        await message.answer(
            f"Telegram accepted the {language.upper()} message (ID {sent.message_id}), but the "
            "database could not finalize it. Check the channel and database before proceeding."
        )
        return
    await message.answer(
        f"Published {language.upper()} article <code>{article_id}</code> to "
        f"<code>{html.escape(channel_id)}</code>. Telegram message ID: <code>{sent.message_id}</code>."
    )


@router.callback_query(F.data.startswith("ed:"))
async def editorial_callback(
    callback: CallbackQuery,
    settings: Settings,
    editorial_service: EditorialService,
) -> None:
    if not _is_admin_callback(callback, settings):
        await callback.answer("Administrator access required.", show_alert=True)
        return
    if not callback.data:
        await callback.answer("Invalid action.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Invalid action.", show_alert=True)
        return
    _, action, raw_id = parts
    article_id = _parse_article_id(raw_id)
    if article_id is None:
        await callback.answer("Invalid article ID.", show_alert=True)
        return
    target = callback.message
    if not isinstance(target, Message):
        await callback.answer("The original review message is unavailable.", show_alert=True)
        return
    actor_id = callback.from_user.id

    if action == "edit":
        await callback.answer("Use the edit command.")
        await target.answer(
            f"Send <code>/edit {article_id} replacement Telegram text</code>. "
            "The replacement is treated as plain text."
        )
        return

    if action == "approve":
        try:
            await editorial_service.approve_article(article_id, actor_id)
        except (ArticleNotFoundError, ValueError) as exc:
            await callback.answer(str(exc)[:180], show_alert=True)
            return
        except Exception:
            logger.exception("Moderation callback approval failed")
            await callback.answer("Approval failed. Check application logs.", show_alert=True)
            return
        await target.edit_reply_markup(reply_markup=None)
        await callback.answer("Approved. Not published.")
        await target.answer(
            f"Article <code>{article_id}</code> approved. Publishing remains a separate "
            "explicit action: /publish ARTICLE_UUID."
        )
        return

    if action == "reject":
        try:
            await editorial_service.reject_article(
                article_id,
                actor_telegram_id=actor_id,
                reason="Rejected from moderation review keyboard",
            )
        except (ArticleNotFoundError, ValueError) as exc:
            await callback.answer(str(exc)[:180], show_alert=True)
            return
        except Exception:
            logger.exception("Moderation callback rejection failed")
            await callback.answer("Rejection failed. Check application logs.", show_alert=True)
            return
        await target.edit_reply_markup(reply_markup=None)
        await callback.answer("Rejected.")
        await target.answer(f"Article <code>{article_id}</code> rejected and recorded.")
        return

    if action == "regen":
        await callback.answer("Regeneration started.")
        await target.answer("Regenerating the draft. The current review remains active until success…")
        try:
            draft = await editorial_service.draft_article(article_id, actor_telegram_id=actor_id)
            item = await editorial_service.get_review_item(article_id)
        except (
            ArticleNotFoundError,
            EditorialAlreadyRunningError,
            EditorialGenerationError,
            ValueError,
        ) as exc:
            await target.answer(html.escape(str(exc)))
            return
        except Exception:
            logger.exception("Moderation callback regeneration failed")
            await target.answer("Regeneration failed. Check application logs.")
            return
        await target.answer(
            f"New draft created ({html.escape(draft.provider)} / {html.escape(draft.model)})."
        )
        await _send_review(target, item)
        return

    await callback.answer("Unknown action.", show_alert=True)


@router.callback_query(F.data.startswith("tr:"))
async def translation_callback(
    callback: CallbackQuery,
    settings: Settings,
    translation_service: TranslationService,
) -> None:
    if not _is_admin_callback(callback, settings):
        await callback.answer("Administrator access required.", show_alert=True)
        return
    if not callback.data:
        await callback.answer("Invalid action.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) != 3:
        await callback.answer("Invalid action.", show_alert=True)
        return
    _, action, raw_id = parts
    article_id = _parse_article_id(raw_id)
    if article_id is None:
        await callback.answer("Invalid article ID.", show_alert=True)
        return
    target = callback.message
    if not isinstance(target, Message):
        await callback.answer("The original review message is unavailable.", show_alert=True)
        return
    actor_id = callback.from_user.id
    if action == "edit":
        await callback.answer("Use /edit ARTICLE_UUID en TEXT.")
        await target.answer(
            f"Send <code>/edit {article_id} en replacement English text</code>. "
            "The replacement is treated as plain text."
        )
        return
    try:
        if action == "approve":
            await translation_service.approve_translation(article_id, actor_id)
        elif action == "reject":
            await translation_service.reject_translation(
                article_id,
                actor_telegram_id=actor_id,
                reason="Rejected from English moderation review keyboard",
            )
        else:
            await callback.answer("Unknown action.", show_alert=True)
            return
    except (ArticleNotFoundError, ValueError) as exc:
        await callback.answer(str(exc)[:180], show_alert=True)
        return
    except Exception:
        logger.exception("English translation moderation callback failed")
        await callback.answer("Moderation action failed. Check application logs.", show_alert=True)
        return
    await target.edit_reply_markup(reply_markup=None)
    if action == "approve":
        await callback.answer("English translation approved. Not published.")
        await target.answer(
            f"English translation for <code>{article_id}</code> approved. "
            "Publish separately with /publish ARTICLE_UUID en."
        )
    else:
        await callback.answer("English translation rejected.")
        await target.answer(f"English translation for <code>{article_id}</code> rejected and recorded.")
