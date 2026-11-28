import re
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

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

    fsm_storage: Literal["memory", "redis"] = "memory"
    redis_url: SecretStr | None = None
    fsm_key_prefix: str = "tgnews:fsm"
    fsm_state_ttl_seconds: int = 86400
    fsm_data_ttl_seconds: int = 86400

    bot_transport: Literal["polling", "webhook"] = "polling"
    webhook_base_url: str | None = None
    webhook_path: str = "/telegram/webhook"
    webhook_secret_token: SecretStr | None = None
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8080

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
    source_fetch_concurrency: int = 4
    source_persist_batch_size: int = 100
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
    db_slow_query_threshold_ms: int = 250
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_timeout_seconds: float = 30.0
    db_pool_recycle_seconds: int = 1800
    log_level: str = "INFO"
    timezone: str = "UTC"
    ingestion_interval_minutes: int = 60
    ingestion_scheduler_enabled: bool = True

    @field_validator("redis_url", mode="before")
    @classmethod
    def normalize_empty_redis_url(cls, value: SecretStr | str | None) -> SecretStr | str | None:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("webhook_base_url", mode="before")
    @classmethod
    def normalize_webhook_base_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("WEBHOOK_BASE_URL contains an invalid port") from exc
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username is not None
            or port is not None and port not in {80, 88, 443, 8443}
        ):
            raise ValueError("WEBHOOK_BASE_URL must be an HTTPS origin on a Telegram-supported port")
        return normalized

    @field_validator("webhook_secret_token", mode="before")
    @classmethod
    def validate_webhook_secret_token(cls, value: SecretStr | str | None) -> SecretStr | str | None:
        if isinstance(value, str) and not value.strip():
            return None
        secret = value.get_secret_value() if isinstance(value, SecretStr) else value
        if secret is not None and (len(secret) > 256 or not re.fullmatch(r"[A-Za-z0-9_-]+", secret)):
            raise ValueError("WEBHOOK_SECRET_TOKEN must use 1-256 letters, digits, underscores or hyphens")
        return value

    @field_validator("webhook_path")
    @classmethod
    def validate_webhook_path(cls, value: str) -> str:
        if not value.startswith("/") or "?" in value or "#" in value:
            raise ValueError("WEBHOOK_PATH must be an absolute URL path without query or fragment")
        return value

    @field_validator("webhook_host")
    @classmethod
    def validate_webhook_host(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("WEBHOOK_HOST must not be empty")
        return value.strip()

    @field_validator("webhook_port")
    @classmethod
    def validate_webhook_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("WEBHOOK_PORT must be between 1 and 65535")
        return value

    @field_validator("fsm_key_prefix")
    @classmethod
    def validate_fsm_key_prefix(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("FSM_KEY_PREFIX must not be empty")
        return value.strip()

    @field_validator("openai_temperature")
    @classmethod
    def validate_temperature(cls, value: float) -> float:
        if not 0 <= value <= 2:
            raise ValueError("OPENAI_TEMPERATURE must be between 0 and 2")
        return value

    @field_validator(
        "source_fetch_limit",
        "source_fetch_concurrency",
        "source_persist_batch_size",
        "http_max_connections",
        "mrc_article_concurrency",
        "source_retry_attempts",
        "duplicate_lookback_days",
        "duplicate_candidate_limit",
        "db_slow_query_threshold_ms",
        "db_pool_size",
        "db_pool_recycle_seconds",
        "fsm_state_ttl_seconds",
        "fsm_data_ttl_seconds",
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

    @field_validator("db_max_overflow")
    @classmethod
    def validate_db_max_overflow(cls, value: int) -> int:
        if value < 0:
            raise ValueError("DB_MAX_OVERFLOW must not be negative")
        return value

    @field_validator("db_pool_timeout_seconds")
    @classmethod
    def validate_db_pool_timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("DB_POOL_TIMEOUT_SECONDS must be greater than zero")
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

    @property
    def redis_url_value(self) -> str | None:
        return self.redis_url.get_secret_value() if self.redis_url is not None else None

    @property
    def webhook_secret_value(self) -> str | None:
        return (
            self.webhook_secret_token.get_secret_value()
            if self.webhook_secret_token is not None else None
        )

    @property
    def webhook_url(self) -> str | None:
        if self.webhook_base_url is None:
            return None
        return f"{self.webhook_base_url}{self.webhook_path}"

    @property
    def db_pool_capacity_per_instance(self) -> int:
        """Maximum simultaneous DB connections this process can hold."""
        return self.db_pool_size + self.db_max_overflow

    def validate_runtime(self) -> None:
        if self.bot_token is None:
            raise ValueError("BOT_TOKEN is required to run the Telegram bot")
        if self.fsm_storage == "redis" and self.redis_url is None:
            raise ValueError("REDIS_URL is required when FSM_STORAGE=redis")
        if self.bot_transport == "webhook":
            if self.webhook_base_url is None:
                raise ValueError("WEBHOOK_BASE_URL is required when BOT_TRANSPORT=webhook")
            if self.webhook_secret_token is None:
                raise ValueError("WEBHOOK_SECRET_TOKEN is required when BOT_TRANSPORT=webhook")
            if self.drop_pending_updates:
                raise ValueError("DROP_PENDING_UPDATES must be false in webhook mode")
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
