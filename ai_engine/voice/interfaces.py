"""Voice (STT / TTS) integration interfaces and safe text-fallback pipeline."""

from abc import ABC, abstractmethod
import inspect
import logging
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from ai_engine.assistant.service import MultilingualHealthAssistant
from ai_engine.consent.enforcer import ConsentEnforcer
from ai_engine.languages import LanguagePreference, validate_language_code
from ai_engine.schemas.assistant import AssistantChatRequest, AssistantChatResponse
from ai_engine.schemas.consent import ConsentGrant, SharingPurpose

logger = logging.getLogger(__name__)


def construct_spoken_response_text(chat_resp: AssistantChatResponse) -> str:
    """Construct deterministic spoken response text preserving safety context.

    Preserves medical facts, numbers, dosages, and instructions from chat_resp.answer verbatim.
    Appends conflict warnings, uncertainty notes, and non-diagnostic disclaimers only if
    they are not already present in the answer text, avoiding duplicate warnings.
    """
    parts = [chat_resp.answer.strip()]
    normalized_answer = chat_resp.answer.lower()

    # Conflicting information notices
    if chat_resp.conflicting_information:
        for conflict in chat_resp.conflicting_information:
            c_text = conflict.strip()
            if c_text and c_text.lower() not in normalized_answer:
                parts.append(f"Important note on conflicting records: {c_text}")

    # Missing information notices
    if chat_resp.missing_information:
        for missing in chat_resp.missing_information:
            m_text = missing.strip()
            if m_text and m_text.lower() not in normalized_answer:
                parts.append(f"Missing information note: {m_text}")

    # Non-diagnostic disclaimer
    if chat_resp.disclaimer:
        disc = chat_resp.disclaimer.strip()
        if disc and disc.lower() not in normalized_answer:
            parts.append(disc)

    return "\n\n".join(parts)


class VoiceCapabilityStatus(BaseModel):
    """Describes whether STT/TTS is available for a given language."""

    model_config = ConfigDict(extra="forbid")

    language_code: str
    stt_supported: bool = False
    tts_supported: bool = False
    provider_name: str = "none"
    fallback_to_text: bool = True
    limitation_reason: Optional[str] = None


class SpeechToTextResult(BaseModel):
    """Result of converting patient voice input into text."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    transcript: Optional[str] = None
    language_code: str
    detected_language_code: Optional[str] = None
    language_probability: Optional[float] = None
    fallback_to_text: bool = True
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class TextToSpeechResult(BaseModel):
    """Result of synthesizing spoken response audio in the selected language."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    audio_bytes: Optional[bytes] = None
    mime_type: Optional[str] = None
    language_code: str
    voice_id: Optional[str] = None
    model_id: Optional[str] = None
    fallback_to_text: bool = True
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class VoiceTurnResponse(BaseModel):
    """Combined voice-or-text response retaining text interaction on speech limitations."""

    model_config = ConfigDict(extra="forbid")

    assistant_response: Optional[AssistantChatResponse] = None
    stt_result: Optional[SpeechToTextResult] = None
    tts_result: Optional[TextToSpeechResult] = None
    voice_capability: VoiceCapabilityStatus
    consent_applied: bool = False
    delegated_access_authorized: bool = True
    delegated_access_denial_code: Optional[str] = None
    delegated_access_denial_reason: Optional[str] = None


class SpeechToTextProvider(ABC):
    """Abstract interface for multilingual Speech-to-Text providers."""

    @abstractmethod
    def supports_language(self, language_code: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def transcribe(self, audio_bytes: bytes, language_code: Optional[str] = "en") -> SpeechToTextResult:
        raise NotImplementedError


class TextToSpeechProvider(ABC):
    """Abstract interface for multilingual Text-to-Speech providers."""

    @abstractmethod
    def supports_language(self, language_code: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def synthesize(self, text: str, language_code: str) -> TextToSpeechResult:
        raise NotImplementedError


class UnconfiguredSpeechProvider(SpeechToTextProvider, TextToSpeechProvider):
    """Default speech adapter that honestly reports unavailable voice capabilities."""

    def supports_language(self, language_code: str) -> bool:
        validate_language_code(language_code)
        return False

    async def transcribe(self, audio_bytes: bytes, language_code: Optional[str] = "en") -> SpeechToTextResult:
        code = language_code or "en"
        info = validate_language_code(code)
        return SpeechToTextResult(
            success=False,
            transcript=None,
            language_code=info.code,
            fallback_to_text=True,
            error_message=(
                f"Speech-to-text is not configured for {info.name} ({info.code}); "
                "retaining text-based interaction."
            ),
        )

    async def synthesize(self, text: str, language_code: str) -> TextToSpeechResult:
        info = validate_language_code(language_code)
        return TextToSpeechResult(
            success=False,
            audio_bytes=None,
            mime_type=None,
            language_code=info.code,
            fallback_to_text=True,
            error_message=(
                f"Text-to-speech is not configured for {info.name} ({info.code}); "
                "retaining text-based interaction."
            ),
        )


class VoiceAssistantPipeline:
    """Coordinates voice input/output with MultilingualHealthAssistant and backend authorization."""

    def __init__(
        self,
        assistant: Optional[MultilingualHealthAssistant] = None,
        stt_provider: Optional[SpeechToTextProvider] = None,
        tts_provider: Optional[TextToSpeechProvider] = None,
        consent_enforcer: Optional[ConsentEnforcer] = None,
    ):
        self.assistant = assistant or MultilingualHealthAssistant()
        default_speech = UnconfiguredSpeechProvider()
        self.stt_provider = stt_provider or default_speech
        self.tts_provider = tts_provider or default_speech
        self.consent_enforcer = consent_enforcer or ConsentEnforcer()

    async def aclose(self) -> None:
        """Safely release underlying STT and TTS provider resources."""
        for provider in (self.stt_provider, self.tts_provider):
            if hasattr(provider, "aclose") and callable(getattr(provider, "aclose")):
                try:
                    await provider.aclose()
                except Exception as e:
                    logger.debug("Provider aclose caught non-fatal exception: %s", type(e).__name__)

    def get_capability_status(self, language_code: str) -> VoiceCapabilityStatus:
        info = validate_language_code(language_code)
        stt_ok = self.stt_provider.supports_language(info.code)
        tts_ok = self.tts_provider.supports_language(info.code)
        limitation = None
        if not stt_ok or not tts_ok:
            limitation = (
                f"Voice support for {info.name} ({info.code}) is partially or fully unavailable "
                f"(stt={stt_ok}, tts={tts_ok}); text-based interaction remains active."
            )
        provider_label = f"STT: {type(self.stt_provider).__name__}, TTS: {type(self.tts_provider).__name__}"
        return VoiceCapabilityStatus(
            language_code=info.code,
            stt_supported=stt_ok,
            tts_supported=tts_ok,
            provider_name=provider_label,
            fallback_to_text=not (stt_ok and tts_ok),
            limitation_reason=limitation,
        )

    async def _resolve_records_authorization(
        self,
        verified_records: list[dict[str, Any]],
        patient_id: Optional[str],
        recipient_id: Optional[str],
        sharing_purpose: Optional[SharingPurpose],
        consent_grant: Optional[ConsentGrant],
    ) -> tuple[bool, list[dict[str, Any]], Optional[str], Optional[str]]:
        """Validate authorization for shared/delegated records.

        Direct patient self-use (recipient_id is None or recipient_id == patient_id)
        preserves direct access without requiring an external consent grant.
        Delegated access strictly requires a valid, active backend consent grant.
        """
        # Direct patient self-use
        if recipient_id is None or (patient_id is not None and recipient_id == patient_id):
            return True, verified_records, None, None

        # Delegated access requires patient_id, purpose, and backend verification
        if not patient_id:
            return False, [], "MISSING_PATIENT_ID", "Delegated access requires an explicit patient_id."

        purpose = sharing_purpose or SharingPurpose.CAREGIVER_VIEW

        evaluation = await self.consent_enforcer.evaluate_and_filter(
            patient_id=patient_id,
            recipient_id=recipient_id,
            purpose=purpose,
            records=verified_records,
            consent=consent_grant,
        )

        if not evaluation.authorized:
            return False, [], evaluation.denial_code, evaluation.denial_reason

        return True, evaluation.filtered_records, None, None

    async def handle_text_with_optional_tts(
        self,
        question: str,
        verified_records: list[dict[str, Any]],
        language_code: str = "en",
        source_language: Optional[str] = None,
        speak_response: bool = False,
        tts_consent_granted: bool = False,
        patient_id: Optional[str] = None,
        recipient_id: Optional[str] = None,
        sharing_purpose: Optional[SharingPurpose] = None,
        consent_grant: Optional[ConsentGrant] = None,
    ) -> VoiceTurnResponse:
        """Process a text question and optionally synthesize spoken audio in the selected language.

        tts_consent_granted defaults to False to ensure strict opt-in privacy.
        Delegated patient record access is gated behind explicit backend authorization.
        """
        lang_pref = LanguagePreference(
            language_code=language_code,
            source_language=source_language,
            response_language=language_code,
        )
        cap = self.get_capability_status(lang_pref.response_language or lang_pref.language_code)

        # Gate record access for delegated sessions
        auth_ok, records_to_use, d_code, d_reason = await self._resolve_records_authorization(
            verified_records=verified_records,
            patient_id=patient_id,
            recipient_id=recipient_id,
            sharing_purpose=sharing_purpose,
            consent_grant=consent_grant,
        )
        if not auth_ok:
            return VoiceTurnResponse(
                assistant_response=None,
                tts_result=None,
                voice_capability=cap,
                consent_applied=True,
                delegated_access_authorized=False,
                delegated_access_denial_code=d_code,
                delegated_access_denial_reason=d_reason,
            )

        req = AssistantChatRequest(
            question=question,
            language=lang_pref,
            verified_records=records_to_use,
        )
        chat_resp = await self.assistant.answer_question(req)

        tts_res: Optional[TextToSpeechResult] = None
        if speak_response:
            if not tts_consent_granted:
                tts_res = TextToSpeechResult(
                    success=False,
                    language_code=chat_resp.response_language,
                    fallback_to_text=True,
                    error_code="CONSENT_DENIED",
                    error_message="External text-to-speech processing requires explicit user opt-in consent.",
                )
            else:
                spoken_text = construct_spoken_response_text(chat_resp)
                tts_res = await self.tts_provider.synthesize(
                    spoken_text,
                    chat_resp.response_language,
                )

        return VoiceTurnResponse(
            assistant_response=chat_resp,
            tts_result=tts_res,
            voice_capability=cap,
            consent_applied=True,
            delegated_access_authorized=True,
        )

    async def handle_audio_turn(
        self,
        audio_bytes: bytes,
        verified_records: list[dict[str, Any]],
        language_code: str = "en",
        *,
        stt_consent_granted: bool = False,
        tts_consent_granted: bool = False,
        speak_response: bool = False,
        stt_language_hint: Optional[str] = None,
        declared_mime_type: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        patient_id: Optional[str] = None,
        recipient_id: Optional[str] = None,
        sharing_purpose: Optional[SharingPurpose] = None,
        consent_grant: Optional[ConsentGrant] = None,
    ) -> VoiceTurnResponse:
        """Full voice pipeline: Audio -> STT -> BridgeCare Assistant -> optional TTS.

        Enforces explicit opt-in consent for external STT and TTS processing.
        Enforces backend ConsentGrant authorization for shared/delegated patient records.
        Preserves medical reasoning, provenance, and grounded truth.
        """
        lang_info = validate_language_code(language_code)
        cap = self.get_capability_status(lang_info.code)

        if not stt_consent_granted:
            return VoiceTurnResponse(
                assistant_response=None,
                stt_result=SpeechToTextResult(
                    success=False,
                    language_code=lang_info.code,
                    fallback_to_text=True,
                    error_code="CONSENT_DENIED",
                    error_message=(
                        "External speech-to-text processing denied: explicit user opt-in "
                        "consent is required."
                    ),
                ),
                tts_result=None,
                voice_capability=cap,
                consent_applied=True,
            )

        # Gate record access for delegated sessions before invoking assistant
        auth_ok, records_to_use, d_code, d_reason = await self._resolve_records_authorization(
            verified_records=verified_records,
            patient_id=patient_id,
            recipient_id=recipient_id,
            sharing_purpose=sharing_purpose,
            consent_grant=consent_grant,
        )
        if not auth_ok:
            return VoiceTurnResponse(
                assistant_response=None,
                stt_result=None,
                tts_result=None,
                voice_capability=cap,
                consent_applied=True,
                delegated_access_authorized=False,
                delegated_access_denial_code=d_code,
                delegated_access_denial_reason=d_reason,
            )

        stt_kwargs: dict[str, Any] = {}
        if declared_mime_type is not None:
            stt_kwargs["declared_mime_type"] = declared_mime_type
        if duration_seconds is not None:
            stt_kwargs["duration_seconds"] = duration_seconds

        # Clean invocation checking STT provider method signature
        sig = inspect.signature(self.stt_provider.transcribe)
        takes_kwargs = any(
            p.kind in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
            for p in sig.parameters.values()
        )
        if takes_kwargs:
            stt_res = await self.stt_provider.transcribe(
                audio_bytes,
                stt_language_hint,
                **stt_kwargs,
            )
        else:
            stt_res = await self.stt_provider.transcribe(
                audio_bytes,
                stt_language_hint or lang_info.code,
            )

        if not stt_res.success or not stt_res.transcript or not stt_res.transcript.strip():
            return VoiceTurnResponse(
                assistant_response=None,
                stt_result=stt_res,
                tts_result=None,
                voice_capability=cap,
                consent_applied=True,
                delegated_access_authorized=True,
            )

        effective_source_lang = stt_res.detected_language_code or stt_language_hint
        lang_pref = LanguagePreference(
            language_code=lang_info.code,
            source_language=effective_source_lang,
            response_language=lang_info.code,
        )
        chat_req = AssistantChatRequest(
            question=stt_res.transcript.strip(),
            language=lang_pref,
            verified_records=records_to_use,
        )
        chat_resp = await self.assistant.answer_question(chat_req)

        tts_res: Optional[TextToSpeechResult] = None
        if speak_response:
            if not tts_consent_granted:
                tts_res = TextToSpeechResult(
                    success=False,
                    language_code=chat_resp.response_language,
                    fallback_to_text=True,
                    error_code="CONSENT_DENIED",
                    error_message=(
                        "External text-to-speech processing denied: explicit user opt-in "
                        "consent is required."
                    ),
                )
            else:
                spoken_text = construct_spoken_response_text(chat_resp)
                tts_res = await self.tts_provider.synthesize(
                    spoken_text,
                    chat_resp.response_language,
                )

        return VoiceTurnResponse(
            assistant_response=chat_resp,
            stt_result=stt_res,
            tts_result=tts_res,
            voice_capability=cap,
            consent_applied=True,
            delegated_access_authorized=True,
        )
