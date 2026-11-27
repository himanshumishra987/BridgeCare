"""ElevenLabs Text-to-Speech (Eleven v4) adapter for BridgeCare."""

import asyncio
import logging
from typing import Any, Optional

from elevenlabs import AsyncElevenLabs, VoiceSettings
from elevenlabs.core.api_error import ApiError

from ai_engine.languages import validate_language_code
from ai_engine.voice.config import SUPPORTED_HTTP_TTS_MODELS, VoiceConfig
from ai_engine.voice.interfaces import TextToSpeechProvider, TextToSpeechResult

logger = logging.getLogger(__name__)

_OUTPUT_FORMAT_MIME: dict[str, str] = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "opus": "audio/opus",
    "pcm": "audio/pcm",
    "ulaw": "audio/basic",
    "alaw": "audio/basic",
}


def _mime_for_output_format(fmt: str) -> str:
    prefix = fmt.split("_", 1)[0].lower()
    return _OUTPUT_FORMAT_MIME.get(prefix, "audio/mpeg")


class ElevenLabsTTSProvider(TextToSpeechProvider):
    """Opt-in ElevenLabs TTS adapter with per-language voice configuration, safe fallback, and client caching."""

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
        """Synchronous accessor for capability checks."""
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
                        logger.debug("TTS client aclose caught non-fatal exception: %s", type(e).__name__)

    def supports_language(self, language_code: str) -> bool:
        info = validate_language_code(language_code)
        if not self.config.elevenlabs_tts_enabled:
            return False
        if self._get_client_sync() is None:
            return False
        return self.config.get_voice_id(info.code) is not None

    async def synthesize(self, text: str, language_code: str) -> TextToSpeechResult:
        """Synthesize speech in the explicitly selected language using its configured voice_id.

        Never silently falls back to a different language or unconfigured voice.
        Validates model compatibility before invoking external HTTP endpoint.
        """
        info = validate_language_code(language_code)

        if not self.config.elevenlabs_tts_enabled:
            return TextToSpeechResult(
                success=False,
                language_code=info.code,
                fallback_to_text=True,
                error_code="TTS_DISABLED",
                error_message="External text-to-speech is disabled (opt-in required).",
            )

        # Check model compatibility: eleven_v4_turbo requires WebSocket, not HTTP convert
        if self.config.elevenlabs_tts_model == "eleven_v4_turbo":
            return TextToSpeechResult(
                success=False,
                language_code=info.code,
                fallback_to_text=True,
                error_code="INCOMPATIBLE_MODEL",
                error_message=(
                    "Model 'eleven_v4_turbo' requires WebSocket Text-to-Dialogue streaming "
                    "and is not supported on the HTTP text_to_speech.convert endpoint. "
                    "Configure 'eleven_v4' for HTTP synthesis."
                ),
            )

        if self.config.elevenlabs_tts_model not in SUPPORTED_HTTP_TTS_MODELS:
            return TextToSpeechResult(
                success=False,
                language_code=info.code,
                fallback_to_text=True,
                error_code="UNSUPPORTED_TTS_MODEL",
                error_message=(
                    f"Configured TTS model '{self.config.elevenlabs_tts_model}' is not in "
                    f"supported HTTP models: {sorted(SUPPORTED_HTTP_TTS_MODELS)}."
                ),
            )

        client = await self._get_client()
        if client is None:
            return TextToSpeechResult(
                success=False,
                language_code=info.code,
                fallback_to_text=True,
                error_code="MISSING_API_KEY",
                error_message="ELEVENLABS_API_KEY is not configured for text-to-speech.",
            )

        voice_id = self.config.get_voice_id(info.code)
        if not voice_id:
            return TextToSpeechResult(
                success=False,
                language_code=info.code,
                fallback_to_text=True,
                error_code="VOICE_NOT_CONFIGURED",
                error_message=(
                    f"No ElevenLabs voice_id is configured for {info.name} ({info.code}); "
                    "retaining text-based interaction."
                ),
            )

        if not text or not text.strip():
            return TextToSpeechResult(
                success=False,
                language_code=info.code,
                voice_id=voice_id,
                fallback_to_text=True,
                error_code="EMPTY_TEXT",
                error_message="Cannot synthesize empty text.",
            )

        # Eleven v4 models support stability and similarity_boost
        voice_settings = VoiceSettings(stability=0.5, similarity_boost=0.75)
        max_attempts = 1 + self.config.elevenlabs_max_retries
        last_code = "TTS_ERROR"
        last_msg = "Text-to-speech synthesis failed."

        tts_kwargs: dict[str, Any] = {
            "model_id": self.config.elevenlabs_tts_model,
            "language_code": info.code,
            "output_format": self.config.elevenlabs_tts_output_format,
            "voice_settings": voice_settings,
        }
        if self.config.elevenlabs_enable_logging is not None:
            tts_kwargs["enable_logging"] = self.config.elevenlabs_enable_logging

        for attempt in range(max_attempts):
            try:
                async def _collect_audio() -> bytes:
                    stream = client.text_to_speech.convert(
                        voice_id,
                        text=text.strip(),
                        **tts_kwargs,
                    )
                    chunks: list[bytes] = []
                    async for chunk in stream:
                        if chunk:
                            chunks.append(chunk)
                    return b"".join(chunks)

                audio_bytes = await asyncio.wait_for(
                    _collect_audio(),
                    timeout=self.config.elevenlabs_timeout_seconds,
                )

                if not audio_bytes:
                    return TextToSpeechResult(
                        success=False,
                        language_code=info.code,
                        voice_id=voice_id,
                        fallback_to_text=True,
                        error_code="EMPTY_TTS_OUTPUT",
                        error_message="ElevenLabs TTS returned empty audio bytes.",
                    )

                return TextToSpeechResult(
                    success=True,
                    audio_bytes=audio_bytes,
                    mime_type=_mime_for_output_format(self.config.elevenlabs_tts_output_format),
                    language_code=info.code,
                    voice_id=voice_id,
                    model_id=self.config.elevenlabs_tts_model,
                    fallback_to_text=False,
                )

            except asyncio.TimeoutError:
                last_code = "TTS_TIMEOUT"
                last_msg = (
                    f"ElevenLabs TTS timed out after {self.config.elevenlabs_timeout_seconds:.1f}s."
                )
                logger.warning("ElevenLabs TTS attempt %d timed out.", attempt + 1)
            except ApiError as err:
                status = getattr(err, "status_code", 0)
                if status == 429:
                    last_code = "RATE_LIMIT_EXCEEDED"
                    last_msg = "ElevenLabs TTS rate limit exceeded (HTTP 429)."
                elif status in (401, 403):
                    last_code = "AUTHENTICATION_FAILED"
                    last_msg = "Invalid or unauthorized ELEVENLABS_API_KEY."
                    break
                elif status == 402:
                    last_code = "QUOTA_OR_PLAN_ERROR"
                    last_msg = "ElevenLabs TTS quota exceeded or paid plan required."
                    break
                else:
                    last_code = "API_ERROR"
                    last_msg = f"ElevenLabs TTS API error (status {status})."
                logger.warning("ElevenLabs TTS API error status=%d on attempt %d", status, attempt + 1)
            except Exception as exc:
                last_code = "UNEXPECTED_ERROR"
                last_msg = f"Unexpected error during TTS: {type(exc).__name__}"
                logger.warning("ElevenLabs TTS unexpected exception: %s", type(exc).__name__)

            if attempt < max_attempts - 1 and self.config.elevenlabs_retry_base_delay_seconds > 0:
                await asyncio.sleep(self.config.elevenlabs_retry_base_delay_seconds * (2 ** attempt))

        return TextToSpeechResult(
            success=False,
            audio_bytes=None,
            mime_type=None,
            language_code=info.code,
            voice_id=voice_id,
            fallback_to_text=True,
            error_code=last_code,
            error_message=last_msg,
        )
