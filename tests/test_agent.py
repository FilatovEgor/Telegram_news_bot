import asyncio
import json
from types import SimpleNamespace

from app.ai.agent import EditorialAgent


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self):
        self.calls = 0

    async def create_chat_completion(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            arguments = json.dumps({"text": "one two three", "max_words": 5})
            call = SimpleNamespace(
                id="tool-1",
                function=SimpleNamespace(name="check_word_count", arguments=arguments),
                model_dump=lambda exclude_none=True: {
                    "id": "tool-1",
                    "type": "function",
                    "function": {"name": "check_word_count", "arguments": arguments},
                },
            )
            message = SimpleNamespace(content=None, tool_calls=[call])
        else:
            message = SimpleNamespace(content="Краткое изложение новости.", tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_editorial_agent_executes_allowlisted_tool_and_finishes():
    provider = FakeProvider()
    result = asyncio.run(
        EditorialAgent(provider).draft_summary(
            "Заголовок", "Текст новости", "https://example.com/news"
        )
    )
    assert result == "Краткое изложение новости."
    assert provider.calls == 2
