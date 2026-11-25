import asyncio

import pytest

from app.ai.tools import check_word_count, format_telegram_draft


def test_word_count_tool():
    result = asyncio.run(check_word_count("one two three", max_words=2))
    assert result == {"word_count": 3, "max_words": 2, "valid": False}


def test_draft_formatter_escapes_html_and_accepts_only_http_urls():
    result = asyncio.run(
        format_telegram_draft(
            "<headline>",
            "A & B",
            "https://example.com/?a=1&b=2",
            ["#news"],
        )
    )
    assert "&lt;headline&gt;" in result["html"]
    assert "A &amp; B" in result["html"]
    assert "#news" in result["html"]
    with pytest.raises(ValueError):
        asyncio.run(format_telegram_draft("title", "summary", "javascript:alert(1)"))
