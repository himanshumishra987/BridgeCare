"""Configuration settings for BridgeCare AI providers."""

from enum import Enum
from typing import Optional

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AIProviderType(str, Enum):
    """Supported AI provider backends."""

    GEMINI = "gemini"
    MOCK = "mock"


class AIProviderConfig(BaseSettings):
    """Environment-driven configuration for AI providers.

    Uses SecretStr for API keys so credentials are never printed or exposed in logs.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    bridgecare_ai_provider: str = Field(
        default=AIProviderType.MOCK.value,
        validation_alias=AliasChoices("BRIDGECARE_AI_PROVIDER", "bridgecare_ai_provider"),
    )
    gemini_api_key: Optional[SecretStr] = Field(
        default=None,
        validation_alias=AliasChoices("GEMINI_API_KEY", "gemini_api_key"),
    )
    gemini_model: str = Field(
        default="gemini-3.8-flash",
        validation_alias=AliasChoices("GEMINI_MODEL", "gemini_model"),
    )
    gemini_timeout_seconds: float = Field(
        default=30.0,
        gt=0.0,
        validation_alias=AliasChoices("GEMINI_TIMEOUT_SECONDS", "gemini_timeout_seconds"),
    )
    gemini_max_retries: int = Field(
        default=2,
        ge=0,
        le=10,
        validation_alias=AliasChoices("GEMINI_MAX_RETRIES", "gemini_max_retries"),
    )
    gemini_retry_base_delay_seconds: float = Field(
        default=0.5,
        ge=0.0,
        validation_alias=AliasChoices("GEMINI_RETRY_BASE_DELAY_SECONDS", "gemini_retry_base_delay_seconds"),
    )
