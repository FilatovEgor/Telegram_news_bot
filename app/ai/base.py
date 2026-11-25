from typing import Any, Protocol


class AIProvider(Protocol):
    name: str
    model: str

    async def create_chat_completion(self, **kwargs: Any) -> Any: ...
    async def close(self) -> None: ...
