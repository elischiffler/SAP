import re
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )
    openai_api_key: SecretStr | None = None
    classifier_model: str = "gpt-6-luna"
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "alloy"
    classifier_provider: Literal["openai", "demo"] = "openai"
    tts_provider: Literal["openai", "macos"] = "openai"
    data_dir: Path = ROOT / "data"
    lease_seconds: int = Field(default=90, ge=10, le=600)
    max_delivery_attempts: int = Field(default=5, ge=1, le=10)
    max_pending_notifications: int = Field(default=100, ge=1, le=1000)
    max_audio_bytes: int = Field(default=5_000_000, ge=1024, le=10_000_000)
    max_audio_seconds: int = Field(default=45, ge=1, le=60)
    provider_timeout_seconds: float = Field(default=25, gt=0, le=120)
    max_provider_calls: int = Field(default=5000, ge=0, le=10000)
    grouping_delay_seconds: float = Field(default=2, ge=0, le=10)
    grouping_window_seconds: float = Field(default=60, ge=0, le=3600)
    max_group_notifications: int = Field(default=50, ge=2, le=50)
    classification_batch_wait_seconds: float = Field(default=0.5, ge=0, le=2)
    environment: Literal["local", "production"] = "local"
    public_host: str | None = None
    esp_timezone: str = "America/Los_Angeles"
    esp_ingest_token: SecretStr | None = None

    @field_validator("esp_timezone")
    @classmethod
    def valid_esp_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("ESP_TIMEZONE must be an IANA timezone") from None
        return value

    @field_validator("esp_ingest_token")
    @classmethod
    def valid_esp_token(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            token = value.get_secret_value()
            if (
                not 32 <= len(token) <= 256
                or not token.isascii()
                or any(c.isspace() for c in token)
            ):
                raise ValueError("ESP_INGEST_TOKEN must be 32–256 non-whitespace ASCII characters")
        return value

    @field_validator("public_host")
    @classmethod
    def valid_public_host(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        if len(value) > 253 or not re.fullmatch(
            r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
            r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?",
            value,
        ):
            raise ValueError("PUBLIC_HOST must be a DNS hostname without scheme, path, or port")
        return value

    @model_validator(mode="after")
    def production_configuration(self) -> "Settings":
        if self.environment == "production":
            if self.public_host is None:
                raise ValueError(
                    "Production requires PUBLIC_HOST and the authenticated HTTPS proxy"
                )
            if self.classifier_provider != "openai" or self.tts_provider != "openai":
                raise ValueError("Production requires hosted classification and speech providers")
            if self.openai_api_key is None or not self.openai_api_key.get_secret_value().strip():
                raise ValueError("Production requires an OpenAI API key")
        return self
