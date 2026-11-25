import html
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

ToolHandler = Callable[..., Any | Awaitable[Any]]


@dataclass(slots=True, frozen=True)
class AgentTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def openai_schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


async def check_word_count(text: str, max_words: int = 200) -> dict[str, Any]:
    if not 1 <= max_words <= 1000:
        raise ValueError("max_words must be between 1 and 1000")
    count = len(text.split())
    return {"word_count": count, "max_words": max_words, "valid": count <= max_words}


async def format_telegram_draft(title: str, summary: str, source_url: str, hashtags: list[str] | None = None) -> dict[str, str]:
    parsed_url = urlsplit(source_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("source_url must be an absolute HTTP(S) URL")
    tags = " ".join(html.escape(tag) for tag in (hashtags or []) if tag.startswith("#"))
    body = f'<a href="{html.escape(source_url, quote=True)}"><b>{html.escape(title)}</b></a>\n{html.escape(summary)}'
    if tags:
        body += f"\n\n<i>{tags}</i>"
    return {"html": body}


def default_tools() -> list[AgentTool]:
    return [
        AgentTool("check_word_count", "Check whether a draft respects the editorial word limit.", {
            "type": "object", "properties": {"text": {"type": "string"}, "max_words": {"type": "integer", "minimum": 1, "maximum": 1000}},
            "required": ["text"], "additionalProperties": False,
        }, check_word_count),
        AgentTool("format_telegram_draft", "Format a draft as a safe Telegram HTML preview. Does not publish it.", {
            "type": "object", "properties": {"title": {"type": "string"}, "summary": {"type": "string"}, "source_url": {"type": "string"}, "hashtags": {"type": "array", "items": {"type": "string"}}},
            "required": ["title", "summary", "source_url"], "additionalProperties": False,
        }, format_telegram_draft),
    ]
