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
        if self.model.startswith("gpt-6-"):
            # GPT-6 Luna supports Chat Completions function calling only at effort=none.
            kwargs.setdefault("reasoning_effort", "none")
            # GPT-6 reasoning models reject custom sampling parameters.
            kwargs.pop("temperature", None)
            if "max_tokens" in kwargs:
                kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
        else:
            kwargs.setdefault("temperature", self.temperature)
            if "max_completion_tokens" in kwargs:
                kwargs["max_tokens"] = kwargs.pop("max_completion_tokens")
        return await self._client.chat.completions.create(**kwargs)

    async def close(self) -> None:
        await self._client.close()
