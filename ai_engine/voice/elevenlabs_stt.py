"""ElevenLabs Speech-to-Text (Scribe) adapter for BridgeCare."""

import asyncio
import io
import logging
from typing import Any, Optional

from elevenlabs import AsyncElevenLabs
from elevenlabs.core.api_error import ApiError

from ai_engine.languages import LANGUAGE_REGISTRY, validate_language_code
from ai_engine.voice.audio_validator import validate_audio_bytes
from ai_engine.voice.config import VoiceConfig
from ai_engine.voice.interfaces import SpeechToTextProvider, SpeechToTextResult

logger = logging.getLogger(__name__)

# BridgeCare ISO 639-1 -> ElevenLabs Scribe ISO 639-3 mapping for all 10 languages
BRIDGECARE_TO_ELEVENLABS_STT_LANG: dict[str, str] = {
    code: info.tesseract_code for code, info in LANGUAGE_REGISTRY.items()
}
_ELEVENLABS_TO_BRIDGECARE_LANG: dict[str, str] = {
    **{v: k for k, v in BRIDGECARE_TO_ELEVENLABS_STT_LANG.items()},
    **{k: k for k in BRIDGECARE_TO_ELEVENLABS_STT_LANG.keys()},
}


class ElevenLabsSTTProvider(SpeechToTextProvider):
    """Opt-in ElevenLabs Scribe STT adapter with audio validation, timeouts, retries, and client caching."""

    def __init__(
        self,
        config: Optional[VoiceConfig] = None,
        client: Optional[AsyncElevenLabs] = None,
    ):
        self.config = config or VoiceConfig()
        self._injected_client = client
        self._cached_client: Optional[AsyncElevenLabs] = None
        self._lock: Optional[asyncio.Lock] = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _get_client_sync(self) -> Optional[AsyncElevenLabs]:
        """Synchronous accessor for health / capability checks."""
        if self._injected_client is not None:
            return self._injected_client
        if self._cached_client is not None:
            return self._cached_client
        key = (
            self.config.elevenlabs_api_key.get_secret_value().strip()
            if self.config.elevenlabs_api_key
            else ""
        )
        if not key:
            return None
        self._cached_client = AsyncElevenLabs(api_key=key)
        return self._cached_client

    async def _get_client(self) -> Optional[AsyncElevenLabs]:
        """Thread/coroutine-safe accessor that caches the AsyncElevenLabs client instance."""
        if self._injected_client is not None:
            return self._injected_client
        if self._cached_client is not None:
            return self._cached_client
        async with self._get_lock():
            if self._cached_client is not None:
                return self._cached_client
            key = (
                self.config.elevenlabs_api_key.get_secret_value().strip()
                if self.config.elevenlabs_api_key
                else ""
            )
            if not key:
                return None
            self._cached_client = AsyncElevenLabs(api_key=key)
            return self._cached_client

    async def aclose(self) -> None:
        """Safely close underlying HTTP client connection pool and release resources."""
        if self._cached_client is None:
            return
        async with self._get_lock():
            if self._cached_client is not None:
                client = self._cached_client
                self._cached_client = None
                wrapper = getattr(client, "_client_wrapper", None)
                httpx_client = getattr(wrapper, "httpx_client", None)
                if httpx_client is not None and hasattr(httpx_client, "aclose"):
                    try:
                        await httpx_client.aclose()
                    except Exception as e:
                        logger.debug("STT client aclose caught non-fatal exception: %s", type(e).__name__)

    def supports_language(self, language_code: str) -> bool:
        info = validate_language_code(language_code)
        if not self.config.elevenlabs_stt_enabled:
            return False
        # scribe_v2_medical only supports English
        if self.config.elevenlabs_stt_model == "scribe_v2_medical" and info.code != "en":
            return False
        return self._get_client_sync() is not None

    async def transcribe(
        self,
        audio_bytes: bytes,
        language_code: Optional[str] = "en",
        *,
        declared_mime_type: Optional[str] = None,
        duration_seconds: Optional[float] = None,
    ) -> SpeechToTextResult:
        """Validate audio bytes in-memory and transcribe via ElevenLabs Scribe.

        When language_code is None, allows Scribe automatic language detection.
        Never logs raw audio, transcripts, or API keys.
        """
        target_lang_code = "en"
        elevenlabs_lang_hint: Optional[str] = None

        if language_code is not None:
            info = validate_language_code(language_code)
            target_lang_code = info.code
            elevenlabs_lang_hint = BRIDGECARE_TO_ELEVENLABS_STT_LANG[info.code]

        if not self.config.elevenlabs_stt_enabled:
            return SpeechToTextResult(
                success=False,
                language_code=target_lang_code,
                fallback_to_text=True,
                error_code="STT_DISABLED",
                error_message="External speech-to-text is disabled (opt-in required).",
            )

        # Model validation: scribe_v2_medical only supports English
        if self.config.elevenlabs_stt_model == "scribe_v2_medical" and target_lang_code != "en":
            return SpeechToTextResult(
                success=False,
                language_code=target_lang_code,
                fallback_to_text=True,
                error_code="UNSUPPORTED_LANGUAGE_FOR_MODEL",
                error_message=(
                    f"Model 'scribe_v2_medical' only supports English ('en'); "
                    f"requested language '{target_lang_code}' is incompatible."
                ),
            )

        client = await self._get_client()
        if client is None:
            return SpeechToTextResult(
                success=False,
                language_code=target_lang_code,
                fallback_to_text=True,
                error_code="MISSING_API_KEY",
                error_message="ELEVENLABS_API_KEY is not configured for speech-to-text.",
            )

        validation = validate_audio_bytes(
            audio_bytes,
            config=self.config,
            declared_mime_type=declared_mime_type,
            duration_seconds=duration_seconds,
        )
        if not validation.is_valid:
            return SpeechToTextResult(
                success=False,
                language_code=target_lang_code,
                fallback_to_text=True,
                error_code=validation.error_code,
                error_message=validation.error_message,
            )

        kwargs: dict[str, Any] = {
            "model_id": self.config.elevenlabs_stt_model,
            "file": (
                validation.filename,
                io.BytesIO(audio_bytes),
                validation.detected_mime_type or "audio/wav",
            ),
        }
        if elevenlabs_lang_hint is not None:
            kwargs["language_code"] = elevenlabs_lang_hint
        if self.config.elevenlabs_stt_model == "scribe_v3":
            kwargs["numbers_format"] = "digits"

        # Explicit Zero-Retention Mode configuration (enterprise account required)
        if self.config.elevenlabs_enable_logging is not None:
            kwargs["enable_logging"] = self.config.elevenlabs_enable_logging

        max_attempts = 1 + self.config.elevenlabs_max_retries
        last_code = "STT_ERROR"
        last_msg = "Speech-to-text transcription failed."

        for attempt in range(max_attempts):
            try:
                # Rewind BytesIO buffer on retry
                kwargs["file"][1].seek(0)
                response = await asyncio.wait_for(
                    client.speech_to_text.convert(**kwargs),
                    timeout=self.config.elevenlabs_timeout_seconds,
                )

                transcript = (getattr(response, "text", None) or "").strip()
                if not transcript:
                    return SpeechToTextResult(
                        success=False,
                        transcript=None,
                        language_code=target_lang_code,
                        fallback_to_text=True,
                        error_code="EMPTY_TRANSCRIPT",
                        error_message="Audio contained no recognizable speech.",
                    )

                raw_detected = getattr(response, "language_code", None)
                mapped_detected = (
                    _ELEVENLABS_TO_BRIDGECARE_LANG.get(str(raw_detected).lower())
                    if raw_detected
                    else None
                )
                detected_lang = mapped_detected or target_lang_code

                raw_prob = getattr(response, "language_probability", None)
                prob_float: Optional[float] = None
                if raw_prob is not None:
                    try:
                        prob_float = float(raw_prob)
                    except (ValueError, TypeError):
                        prob_float = None

                return SpeechToTextResult(
                    success=True,
                    transcript=transcript,
                    language_code=detected_lang,
                    detected_language_code=mapped_detected,
                    language_probability=prob_float,
                    fallback_to_text=False,
                )

            except asyncio.TimeoutError:
                last_code = "STT_TIMEOUT"
                last_msg = (
                    f"ElevenLabs STT timed out after {self.config.elevenlabs_timeout_seconds:.1f}s."
                )
                logger.warning("ElevenLabs STT attempt %d timed out.", attempt + 1)
            except ApiError as err:
                status = getattr(err, "status_code", 0)
                if status == 429:
                    last_code = "RATE_LIMIT_EXCEEDED"
                    last_msg = "ElevenLabs STT rate limit exceeded (HTTP 429)."
                elif status in (401, 403):
                    last_code = "AUTHENTICATION_FAILED"
                    last_msg = "Invalid or unauthorized ELEVENLABS_API_KEY."
                    break
                elif status == 402:
                    last_code = "QUOTA_OR_PLAN_ERROR"
                    last_msg = "ElevenLabs STT quota exceeded or paid plan required."
                    break
                else:
                    last_code = "API_ERROR"
                    last_msg = f"ElevenLabs STT API error (status {status})."
                logger.warning("ElevenLabs STT API error status=%d on attempt %d", status, attempt + 1)
            except Exception as exc:
                last_code = "UNEXPECTED_ERROR"
                last_msg = f"Unexpected error during STT: {type(exc).__name__}"
                logger.warning("ElevenLabs STT unexpected exception: %s", type(exc).__name__)

            if attempt < max_attempts - 1 and self.config.elevenlabs_retry_base_delay_seconds > 0:
                await asyncio.sleep(self.config.elevenlabs_retry_base_delay_seconds * (2 ** attempt))

        return SpeechToTextResult(
            success=False,
            transcript=None,
            language_code=target_lang_code,
            fallback_to_text=True,
            error_code=last_code,
            error_message=last_msg,
        )
