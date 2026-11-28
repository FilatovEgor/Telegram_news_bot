from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")

    bot_token: SecretStr | None = None
    moderation_chat_id: str | None = None
    publish_channel_id: str | None = None
    publish_channel_id_en: str | None = None
    admin_ids: str = ""
    drop_pending_updates: bool = False
    database_url: SecretStr

    ai_provider: Literal["openai", "gigachat"] = "openai"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-6-luna"
    openai_temperature: float = 0.2
    gigachat_credentials: SecretStr | None = None
    gigachat_model: str = "GigaChat"
    ai_request_timeout_seconds: float = 45.0
    ai_run_timeout_seconds: float = 90.0
    ai_retry_attempts: int = 2
    ai_retry_base_delay_seconds: float = 0.5
    ai_max_concurrent_requests: int = 3
    ai_max_editorial_concurrency: int = 2
    ai_max_translation_concurrency: int = 1
    ai_max_tool_rounds: int = 3
    ai_max_input_chars: int = 24000
    ai_max_completion_tokens_per_request: int = 1000
    ai_max_completion_tokens_per_article: int = 1800
    ai_summary_max_words: int = 200

    mrc_enabled: bool = True
    mrc_listing_url: str = "https://www.mrc.ru/ajax/news/?query=&condition=OR"
    rss_feeds: str = ""
    source_fetch_limit: int = 50
    http_timeout_seconds: float = 20.0
    http_max_connections: int = 20
    mrc_article_concurrency: int = 5
    source_retry_attempts: int = 3
    source_retry_base_delay_seconds: float = 0.25
    source_retry_max_delay_seconds: float = 4.0
    source_request_interval_seconds: float = 0.2
    duplicate_lookback_days: int = 30
    duplicate_title_similarity_threshold: float = 0.92
    duplicate_candidate_limit: int = 300
    log_level: str = "INFO"
    timezone: str = "UTC"
    ingestion_interval_minutes: int = 60

    @field_validator("openai_temperature")
    @classmethod
    def validate_temperature(cls, value: float) -> float:
        if not 0 <= value <= 2:
            raise ValueError("OPENAI_TEMPERATURE must be between 0 and 2")
        return value

    @field_validator(
        "source_fetch_limit",
        "http_max_connections",
        "mrc_article_concurrency",
        "source_retry_attempts",
        "duplicate_lookback_days",
        "duplicate_candidate_limit",
        "ingestion_interval_minutes",
        "ai_max_input_chars",
        "ai_max_concurrent_requests",
        "ai_max_editorial_concurrency",
        "ai_max_translation_concurrency",
        "ai_max_completion_tokens_per_request",
        "ai_max_completion_tokens_per_article",
        "ai_summary_max_words",
    )
    @classmethod
    def validate_positive_ints(cls, value: int) -> int:
        if value < 1:
            raise ValueError("This setting must be a positive integer")
        return value

    @field_validator("ai_retry_attempts")
    @classmethod
    def validate_ai_retry_attempts(cls, value: int) -> int:
        if value < 0:
            raise ValueError("AI_RETRY_ATTEMPTS must not be negative")
        return value

    @field_validator("ai_max_tool_rounds")
    @classmethod
    def validate_ai_tool_rounds(cls, value: int) -> int:
        if not 0 <= value <= 8:
            raise ValueError("AI_MAX_TOOL_ROUNDS must be between 0 and 8")
        return value

    @field_validator(
        "http_timeout_seconds",
        "source_retry_base_delay_seconds",
        "source_retry_max_delay_seconds",
        "source_request_interval_seconds",
        "ai_retry_base_delay_seconds",
    )
    @classmethod
    def validate_non_negative_numbers(cls, value: float) -> float:
        if value < 0:
            raise ValueError("This setting must not be negative")
        return value

    @field_validator("ai_request_timeout_seconds", "ai_run_timeout_seconds")
    @classmethod
    def validate_positive_timeouts(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("AI timeouts must be greater than zero")
        return value

    @field_validator("duplicate_title_similarity_threshold")
    @classmethod
    def validate_similarity_threshold(cls, value: float) -> float:
        if not 0 < value <= 1:
            raise ValueError("DUPLICATE_TITLE_SIMILARITY_THRESHOLD must be in (0, 1]")
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

    def publish_channel_for(self, language: str = "ru") -> str | None:
        normalized = language.strip().casefold()
        if normalized == "ru":
            return self.publish_channel_id
        if normalized == "en":
            return self.publish_channel_id_en
        raise ValueError("Only ru and en publishing channels are configured")

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
            raise NotImplementedError("GigaChat provider adapter is an optional follow-up; use AI_PROVIDER=openai")
        _ = self.admin_id_set


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
