import uuid

from app.bot.routers.workflow import (
    _uuid_from_token,
    _uuid_token,
    dashboard_keyboard,
    editorial_review_keyboard,
    translation_review_keyboard,
)


def _callbacks(markup):
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data is not None
    ]


def test_control_deck_exposes_each_primary_workflow_queue():
    callbacks = set(_callbacks(dashboard_keyboard()))
    assert {
        "wf:menu:incoming",
        "wf:menu:review:ru",
        "wf:menu:review:en",
        "wf:menu:sources",
        "wf:menu:fetch",
    } <= callbacks


def test_editorial_and_translation_review_have_complete_button_actions():
    article_id = uuid.uuid4()
    ru = set(_callbacks(editorial_review_keyboard(article_id)))
    en = set(_callbacks(translation_review_keyboard(article_id)))
    assert {
        f"wf:{action}:ru:{article_id}"
        for action in ("edit", "approve", "reject", "regen")
    } <= ru
    assert {
        f"wf:{action}:en:{article_id}"
        for action in ("edit", "approve", "reject", "regen")
    } <= en
    assert f"wf:history:{article_id}" in ru
    assert f"wf:history:{article_id}" in en


def test_compact_publish_confirmation_tokens_round_trip_within_telegram_limit():
    article_id = uuid.uuid4()
    output_id = uuid.uuid4()
    article_token = _uuid_token(article_id)
    output_token = _uuid_token(output_id)
    callback_data = f"wf:confirm:ru:{article_token}:{output_token}"
    assert _uuid_from_token(article_token) == article_id
    assert _uuid_from_token(output_token) == output_id
    assert len(callback_data.encode("utf-8")) <= 64
