from typing import Any

from openai import AsyncOpenAI

from app.config import Settings


class OpenAIProvider:
    """OpenAI Chat Completions adapter with application-managed bounded retries."""

    name = "openai"

    def __init__(self, settings: Settings) -> None:
        if settings.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is required for the OpenAI provider")
        self.model = settings.openai_model
        self.temperature = settings.openai_temperature
        self._client = AsyncOpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.ai_request_timeout_seconds,
            max_retries=0,
        )

    async def create_chat_completion(self, **kwargs: Any) -> Any:
        kwargs.setdefault("model", self.model)
        kwargs.setdefault("temperature", self.temperature)
        return await self._client.chat.completions.create(**kwargs)

    async def close(self) -> None:
        await self._client.close()
