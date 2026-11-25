from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")

    bot_token: SecretStr | None = None
    moderation_chat_id: str | None = None
    publish_channel_id: str | None = None
    admin_ids: str = ""
    drop_pending_updates: bool = False
    database_url: SecretStr

    ai_provider: Literal["openai", "gigachat"] = "openai"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4"
    openai_temperature: float = 0.2
    gigachat_credentials: SecretStr | None = None
    gigachat_model: str = "GigaChat"

    mrc_enabled: bool = True
    mrc_listing_url: str = "https://www.mrc.ru/ajax/news/?query=&condition=OR"
    rss_feeds: str = ""
    source_fetch_limit: int = 50
    http_timeout_seconds: float = 20.0
    http_max_connections: int = 20
    log_level: str = "INFO"
    timezone: str = "UTC"
    ingestion_interval_minutes: int = 60

    @field_validator("openai_temperature")
    @classmethod
    def validate_temperature(cls, value: float) -> float:
        if not 0 <= value <= 2:
            raise ValueError("OPENAI_TEMPERATURE must be between 0 and 2")
        return value

    @field_validator("source_fetch_limit", "http_max_connections", "ingestion_interval_minutes")
    @classmethod
    def validate_positive_ints(cls, value: int) -> int:
        if value < 1:
            raise ValueError("This setting must be a positive integer")
        return value

    @property
    def admin_id_set(self) -> set[int]:
        result: set[int] = set()
        for value in self.admin_ids.split(","):
            value = value.strip()
            if value:
                try:
                    result.add(int(value))
                except ValueError as exc:
                    raise ValueError(f"Invalid Telegram admin ID: {value!r}") from exc
        return result

    @property
    def rss_feed_urls(self) -> list[str]:
        return [item.strip() for item in self.rss_feeds.split(",") if item.strip()]

    @property
    def database_url_value(self) -> str:
        return self.database_url.get_secret_value()

    def validate_runtime(self) -> None:
        if self.bot_token is None:
            raise ValueError("BOT_TOKEN is required to run the Telegram bot")
        if self.ai_provider == "openai" and self.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is required when AI_PROVIDER=openai")
        if self.ai_provider == "gigachat":
            if self.gigachat_credentials is None:
                raise ValueError("GIGACHAT_CREDENTIALS is required when AI_PROVIDER=gigachat")
            raise NotImplementedError("GigaChat provider adapter is an optional follow-up; use AI_PROVIDER=openai in Phase 1")
        _ = self.admin_id_set


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
