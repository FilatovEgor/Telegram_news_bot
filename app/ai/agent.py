import json
import logging
from collections.abc import Sequence
from typing import Any

from app.ai.base import AIProvider
from app.ai.tools import AgentTool, default_tools

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Ты профессиональный аналитик-публицист новостного Telegram-канала. "
    "Подготовь точное, нейтральное и короткое изложение исходной новости не более чем в 200 слов. "
    "Не добавляй факты, которых нет в исходном тексте. Сохраняй имена, числа, единицы измерения "
    "и причинно-следственные связи. Указывай неопределённость, если источник её содержит. "
    "При необходимости используй доступные инструменты для проверки длины и подготовки "
    "HTML-предпросмотра. Никогда не публикуй сообщение самостоятельно."
)


class EditorialAgent:
    """Bounded tool-calling agent; available tools are local and cannot publish."""

    def __init__(self, provider: AIProvider, tools: Sequence[AgentTool] | None = None, max_tool_rounds: int = 4) -> None:
        if max_tool_rounds < 0 or max_tool_rounds > 8:
            raise ValueError("max_tool_rounds must be between 0 and 8")
        self._provider = provider
        self._tools = {tool.name: tool for tool in (tools or default_tools())}
        self._max_tool_rounds = max_tool_rounds

    async def draft_summary(self, title: str, content: str, source_url: str) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Заголовок: {title}\nИсточник: {source_url}\n\nПолный текст новости:\n{content}\n\nПодготовь редакционный черновик. При необходимости используй инструменты для проверки и форматирования."},
        ]
        schemas = [tool.openai_schema() for tool in self._tools.values()]
        for _ in range(self._max_tool_rounds + 1):
            response = await self._provider.create_chat_completion(messages=messages, tools=schemas, tool_choice="auto")
            message = response.choices[0].message
            tool_calls = message.tool_calls or []
            if not tool_calls:
                result = (message.content or "").strip()
                if not result:
                    raise RuntimeError("The AI provider returned an empty editorial draft")
                return result
            messages.append({"role": "assistant", "content": message.content, "tool_calls": [call.model_dump(exclude_none=True) for call in tool_calls]})
            for call in tool_calls:
                tool = self._tools.get(call.function.name)
                try:
                    if tool is None:
                        tool_result: Any = {"error": "Tool is not available"}
                    else:
                        arguments = json.loads(call.function.arguments or "{}")
                        value = tool.handler(**arguments)
                        if hasattr(value, "__await__"):
                            value = await value
                        tool_result = value
                except (TypeError, ValueError, json.JSONDecodeError):
                    logger.warning("Invalid arguments for AI tool %s", call.function.name)
                    tool_result = {"error": "Invalid tool arguments"}
                except Exception:
                    logger.exception("AI tool execution failed: %s", call.function.name)
                    tool_result = {"error": "Tool execution failed"}
                messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(tool_result, ensure_ascii=False)})
        raise RuntimeError("Editorial agent reached its maximum tool-call rounds")
