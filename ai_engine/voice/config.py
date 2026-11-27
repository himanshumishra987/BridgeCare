"""Environment-driven configuration for ElevenLabs Voice Intelligence."""

import os
from typing import Optional

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


# Supported HTTP TTS models for text_to_speech.convert()
SUPPORTED_HTTP_TTS_MODELS = frozenset(
    {
        "eleven_v4",
        "eleven_multilingual_v2",
        "eleven_flash_v2",
        "eleven_flash_v2_5",
        "eleven_turbo_v2_5",
        "eleven_monolingual_v1",
    }
)


class VoiceConfig(BaseSettings):
    """Configuration for ElevenLabs STT and TTS adapters.

    External speech processing is disabled (opt-in) by default.
    API credentials are stored as SecretStr and never logged or exposed.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    elevenlabs_api_key: Optional[SecretStr] = Field(
        default=None,
        validation_alias=AliasChoices("ELEVENLABS_API_KEY", "elevenlabs_api_key"),
    )

    # Opt-in flags for external speech processing
    elevenlabs_stt_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("ELEVENLABS_STT_ENABLED", "elevenlabs_stt_enabled"),
    )
    elevenlabs_tts_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("ELEVENLABS_TTS_ENABLED", "elevenlabs_tts_enabled"),
    )

    # Model and output settings
    elevenlabs_stt_model: str = Field(
        default="scribe_v3",
        validation_alias=AliasChoices("ELEVENLABS_STT_MODEL", "elevenlabs_stt_model"),
    )
    elevenlabs_tts_model: str = Field(
        default="eleven_v4",
        validation_alias=AliasChoices("ELEVENLABS_TTS_MODEL", "elevenlabs_tts_model"),
    )
    elevenlabs_tts_output_format: str = Field(
        default="mp3_44100_128",
        validation_alias=AliasChoices("ELEVENLABS_TTS_OUTPUT_FORMAT", "elevenlabs_tts_output_format"),
    )

    # Zero-Retention Mode configuration (enterprise accounts only)
    # When enable_logging=False, ElevenLabs does not store audio inputs or generated transcripts.
    # NOTE: Configuring enable_logging=False requires an eligible ElevenLabs enterprise contract
    # with Zero-Retention Mode provisioned; standard accounts do not support zero-retention.
    # BridgeCare never silently downgrades privacy settings.
    elevenlabs_enable_logging: Optional[bool] = Field(
        default=None,
        validation_alias=AliasChoices("ELEVENLABS_ENABLE_LOGGING", "elevenlabs_enable_logging"),
    )

    # Per-language voice IDs (never hardcoded across all languages)
    elevenlabs_voice_ids: dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("ELEVENLABS_VOICE_IDS", "elevenlabs_voice_ids"),
    )

    # Safety, timeout, and retry limits
    elevenlabs_timeout_seconds: float = Field(
        default=30.0,
        gt=0.0,
        validation_alias=AliasChoices("ELEVENLABS_TIMEOUT_SECONDS", "elevenlabs_timeout_seconds"),
    )
    elevenlabs_max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        validation_alias=AliasChoices("ELEVENLABS_MAX_RETRIES", "elevenlabs_max_retries"),
    )
    elevenlabs_retry_base_delay_seconds: float = Field(
        default=0.5,
        ge=0.0,
        validation_alias=AliasChoices("ELEVENLABS_RETRY_BASE_DELAY_SECONDS", "elevenlabs_retry_base_delay_seconds"),
    )

    max_audio_size_bytes: int = Field(
        default=25 * 1024 * 1024,
        gt=0,
        validation_alias=AliasChoices("VOICE_MAX_AUDIO_SIZE_BYTES", "max_audio_size_bytes"),
    )
    max_audio_duration_seconds: float = Field(
        default=300.0,
        gt=0.0,
        validation_alias=AliasChoices("VOICE_MAX_AUDIO_DURATION_SECONDS", "max_audio_duration_seconds"),
    )

    def get_voice_id(self, language_code: str) -> Optional[str]:
        """Resolve a configured voice ID for the given language code, or None if unconfigured."""
        code = language_code.strip().lower()
        if code in self.elevenlabs_voice_ids and self.elevenlabs_voice_ids[code].strip():
            return self.elevenlabs_voice_ids[code].strip()
        env_key = f"ELEVENLABS_VOICE_ID_{code.upper()}"
        env_val = os.environ.get(env_key, "").strip()
        return env_val or None
