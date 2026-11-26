import asyncio
from types import SimpleNamespace

from app.ai.openai_provider import OpenAIProvider
from app.config import Settings


class FakeCompletions:
    def __init__(self):
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace()


class FakeAsyncOpenAI:
    def __init__(self, **kwargs):
        self.chat = SimpleNamespace(completions=FakeCompletions())

    async def close(self):
        return None


def test_gpt_6_luna_uses_supported_chat_completion_parameters(monkeypatch):
    monkeypatch.setattr("app.ai.openai_provider.AsyncOpenAI", FakeAsyncOpenAI)
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        openai_api_key="test-key",
        openai_model="gpt-6-luna",
        openai_temperature=0.2,
    )
    provider = OpenAIProvider(settings)

    asyncio.run(
        provider.create_chat_completion(
            messages=[{"role": "user", "content": "test"}],
            tools=[],
            max_completion_tokens=128,
            temperature=0.2,
        )
    )

    kwargs = provider._client.chat.completions.kwargs
    assert kwargs["model"] == "gpt-6-luna"
    assert kwargs["reasoning_effort"] == "none"
    assert kwargs["max_completion_tokens"] == 128
    assert "temperature" not in kwargs


def test_legacy_model_keeps_temperature_and_token_limit_compatibility(monkeypatch):
    monkeypatch.setattr("app.ai.openai_provider.AsyncOpenAI", FakeAsyncOpenAI)
    settings = Settings(
        database_url="postgresql+asyncpg://user:pass@localhost/news",
        openai_api_key="test-key",
        openai_model="gpt-4",
        openai_temperature=0.3,
    )
    provider = OpenAIProvider(settings)

    asyncio.run(
        provider.create_chat_completion(
            messages=[{"role": "user", "content": "test"}],
            max_completion_tokens=64,
        )
    )

    kwargs = provider._client.chat.completions.kwargs
    assert kwargs["model"] == "gpt-4"
    assert kwargs["temperature"] == 0.3
    assert kwargs["max_tokens"] == 64
    assert "max_completion_tokens" not in kwargs
