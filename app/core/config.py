"""Application configuration.

All configuration is read from environment variables prefixed with
``BRIDGECARE_`` (optionally via a local ``.env`` file). Secrets are never
logged, never returned by an API and never written to the repository.
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

logger = logging.getLogger(__name__)

Environment = Literal["development", "test", "staging", "production"]
_NON_DEVELOPMENT = {"staging", "production"}
MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """Runtime settings for the BridgeCare API."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="BRIDGECARE_",
        extra="ignore",
    )

    app_name: str = "BridgeCare API"
    app_description: str = (
        "AI-assisted personal health record organisation and healthcare intelligence platform."
    )
    environment: Environment = "development"
    api_v1_prefix: str = "/api/v1"

    # Cryptographic material -------------------------------------------------
    secret_key: str = ""

    # Database ---------------------------------------------------------------
    database_url: str = "postgresql+psycopg://bridgecare:bridgecare@127.0.0.1:5432/bridgecare"

    # Document storage -------------------------------------------------------
    storage_root: Path = Path("./var/documents")
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1024)
    allowed_document_types: tuple[str, ...] = (
        "application/pdf",
        "image/png",
        "image/jpeg",
    )

    # Token lifetimes --------------------------------------------------------
    access_token_minutes: int = Field(default=30, ge=1, le=1440)
    refresh_token_days: int = Field(default=14, ge=1, le=90)
    share_link_max_days: int = Field(default=30, ge=1, le=365)

    # Internal AI engine contract -------------------------------------------
    ai_service_key: str = ""
    ai_contract_version: str = "2026-02-ai-contract-v1"
    insurance_contract_version: str = "2026-11-insurance-contract-v1"

    # IDTA malware scanning. ``none`` means no scanner is configured, so every
    # document stays ``pending`` and AI processing is refused (never assumed clean).
    document_scanner: Literal["none", "stub"] = "none"

    # Optional external integrations ----------------------------------------
    hospital_directory_provider: str = "none"
    insurer_verification_provider: Literal["none", "stub"] = "none"

    # Operational ------------------------------------------------------------
    allowed_origins: Annotated[tuple[str, ...], NoDecode] = ()
    log_level: str = "INFO"
    default_page_size: int = Field(default=25, ge=1, le=100)
    max_page_size: int = Field(default=100, ge=1, le=500)

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated list (or a JSON array) of origins."""
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(value)
            return tuple(origin.strip() for origin in text.split(",") if origin.strip())
        return value

    @field_validator("secret_key")
    @classmethod
    def _secret_not_placeholder(cls, value: str, info) -> str:
        environment = (info.data or {}).get("environment", "development")
        if environment in _NON_DEVELOPMENT and len(value) < MIN_SECRET_LENGTH:
            raise ValueError(
                "BRIDGECARE_SECRET_KEY must be set to at least 32 characters in staging/production."
            )
        return value

    @model_validator(mode="after")
    def _ensure_secret(self) -> Settings:
        if not self.secret_key:
            if self.environment in _NON_DEVELOPMENT:
                raise ValueError("BRIDGECARE_SECRET_KEY is required.")
            # Ephemeral per-process key so that no insecure constant ships with the code.
            self.secret_key = secrets.token_urlsafe(48)
            logger.warning(
                "BRIDGECARE_SECRET_KEY is unset; generated an ephemeral key for the %s "
                "environment. Sessions will not survive a restart.",
                self.environment,
            )
        return self

    # Convenience lifetime helpers -----------------------------------------
    @property
    def access_token_ttl(self) -> timedelta:
        return timedelta(minutes=self.access_token_minutes)

    @property
    def refresh_token_ttl(self) -> timedelta:
        return timedelta(days=self.refresh_token_days)

    @property
    def resolved_storage_root(self) -> Path:
        return self.storage_root.expanduser().resolve()

    @property
    def ai_contract_enabled(self) -> bool:
        return bool(self.ai_service_key)

    @property
    def scanner_configured(self) -> bool:
        """True only when a real scanner adapter is configured."""
        return self.document_scanner != "none"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
