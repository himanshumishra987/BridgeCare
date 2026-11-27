"""Mocked unit tests for ElevenLabs Voice Intelligence integration."""

import asyncio
import io
import json
import logging
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import wave
from datetime import datetime, timedelta, timezone

from elevenlabs.core.api_error import ApiError
import pytest

from ai_engine.assistant import MultilingualHealthAssistant
from ai_engine.languages import SupportedLanguage, UnsupportedLanguageError
from ai_engine.providers import AIProviderConfig, GeminiProvider
from ai_engine.schemas.assistant import AssistantChatResponse
from ai_engine.schemas.consent import ConsentGrant, ConsentStatus, PermittedDataCategory, SharingPurpose
from ai_engine.voice import (
    BRIDGECARE_TO_ELEVENLABS_STT_LANG,
    ElevenLabsSTTProvider,
    ElevenLabsTTSProvider,
    VoiceAssistantPipeline,
    VoiceConfig,
)
from ai_engine.voice.audio_validator import validate_audio_bytes
from ai_engine.voice.interfaces import construct_spoken_response_text


def _make_valid_wav(duration_secs: float = 0.2, sample_rate: int = 16000, silent: bool = False) -> bytes:
    """Create a synthetic in-memory PCM16 WAV file."""
    num_frames = int(duration_secs * sample_rate)
    bio = io.BytesIO()
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        sample_val = 0 if silent else 1200
        frames = struct.pack(f"<{num_frames}h", *([sample_val] * num_frames))
        wf.writeframes(frames)
    return bio.getvalue()


def _make_voice_config(**overrides) -> VoiceConfig:
    defaults = {
        "elevenlabs_api_key": "synthetic-elevenlabs-secret-key-999",
        "elevenlabs_stt_enabled": True,
        "elevenlabs_tts_enabled": True,
        "elevenlabs_stt_model": "scribe_v3",
        "elevenlabs_tts_model": "eleven_v4",
        "elevenlabs_voice_ids": {"en": "voice-en-123", "hi": "voice-hi-456", "kn": "voice-kn-789"},
        "elevenlabs_timeout_seconds": 5.0,
        "elevenlabs_max_retries": 2,
        "elevenlabs_retry_base_delay_seconds": 0.0,
    }
    defaults.update(overrides)
    return VoiceConfig(_env_file=None, **defaults)


def _make_stt_client(response_obj=None, side_effect=None) -> MagicMock:
    client = MagicMock()
    if side_effect is not None:
        client.speech_to_text.convert = AsyncMock(side_effect=side_effect)
    else:
        client.speech_to_text.convert = AsyncMock(return_value=response_obj)
    return client


def _make_tts_client(chunks: list[bytes] | None = None, side_effect=None) -> MagicMock:
    client = MagicMock()

    async def _gen(*args, **kwargs):
        if side_effect is not None:
            raise side_effect
        for c in (chunks or [b"ID3-mock-mp3-audio"]):
            yield c

    client.text_to_speech.convert = MagicMock(side_effect=_gen)
    return client


def _sample_verified_records() -> list[dict]:
    return [
        {
            "document_id": "doc-lab-1",
            "verification_status": "verified",
            "document_type": "lab_report",
            "document_date": "2026-03-01",
            "biomarkers": [
                {
                    "name": "Hemoglobin",
                    "value": "13.5",
                    "numeric_value": 13.5,
                    "unit": "g/dL",
                    "source_reference": {
                        "document_id": "doc-lab-1",
                        "page_number": 1,
                        "excerpt": "Hemoglobin: 13.5 g/dL",
                    },
                }
            ],
        }
    ]


# =============================================================================
# 1. STT Transcription, Language Mappings & Auto-Detection
# =============================================================================


@pytest.mark.asyncio
async def test_stt_successful_transcription_and_no_phi_or_key_in_logs(caplog):
    """Test STT transcribes valid WAV audio without logging raw audio, transcripts, or API keys."""
    secret_key = "synthetic-elevenlabs-secret-key-999"
    transcript_text = "What is my Hemoglobin level from March 2026?"
    mock_client = _make_stt_client(
        SimpleNamespace(text=transcript_text, language_code="eng", language_probability=0.98)
    )
    stt = ElevenLabsSTTProvider(config=_make_voice_config(elevenlabs_api_key=secret_key), client=mock_client)

    with caplog.at_level(logging.DEBUG):
        res = await stt.transcribe(_make_valid_wav(), language_code="en")

    assert res.success is True
    assert res.transcript == transcript_text
    assert res.language_code == "en"
    assert res.detected_language_code == "en"
    assert res.language_probability == pytest.approx(0.98)
    assert res.fallback_to_text is False
    assert secret_key not in caplog.text
    assert transcript_text not in caplog.text


@pytest.mark.parametrize("lang_enum", list(SupportedLanguage))
@pytest.mark.asyncio
async def test_stt_all_ten_language_code_mappings(lang_enum: SupportedLanguage):
    """Test all 10 BridgeCare language codes map to exact ElevenLabs ISO 639-3 codes."""
    expected_el_code = BRIDGECARE_TO_ELEVENLABS_STT_LANG[lang_enum.value]
    mock_client = _make_stt_client(
        SimpleNamespace(text="Synthetic patient speech", language_code=expected_el_code, language_probability=0.95)
    )
    stt = ElevenLabsSTTProvider(config=_make_voice_config(), client=mock_client)

    res = await stt.transcribe(_make_valid_wav(), language_code=lang_enum.value)
    assert res.success is True
    assert res.language_code == lang_enum.value
    assert mock_client.speech_to_text.convert.call_args.kwargs["language_code"] == expected_el_code


@pytest.mark.asyncio
async def test_stt_automatic_language_detection():
    """Test omitting language_code triggers automatic detection and maps result back."""
    mock_client = _make_stt_client(
        SimpleNamespace(text="ನನ್ನ ಹಿಮೋಗ್ಲೋಬಿನ್ ಎಷ್ಟು?", language_code="kan", language_probability=0.91)
    )
    stt = ElevenLabsSTTProvider(config=_make_voice_config(), client=mock_client)

    res = await stt.transcribe(_make_valid_wav(), language_code=None)
    assert res.success is True
    assert res.detected_language_code == "kn"
    assert res.language_code == "kn"
    assert "language_code" not in mock_client.speech_to_text.convert.call_args.kwargs


# =============================================================================
# 2. TTS Synthesis, Per-Language Voice Selection & Unsupported Languages/Voices
# =============================================================================


@pytest.mark.asyncio
async def test_tts_successful_generation_and_language_specific_voice_selection():
    """Test TTS uses the language-specific configured voice_id and returns audio bytes."""
    mock_client = _make_tts_client([b"chunk1-", b"chunk2"])
    tts = ElevenLabsTTSProvider(config=_make_voice_config(), client=mock_client)

    res = await tts.synthesize("ನಿಮ್ಮ Hemoglobin 13.5 g/dL ಇದೆ.", language_code="kn")
    assert res.success is True
    assert res.audio_bytes == b"chunk1-chunk2"
    assert res.mime_type == "audio/mpeg"
    assert res.voice_id == "voice-kn-789"
    assert res.language_code == "kn"
    assert res.fallback_to_text is False
    assert mock_client.text_to_speech.convert.call_args.args[0] == "voice-kn-789"
    assert mock_client.text_to_speech.convert.call_args.kwargs["language_code"] == "kn"


@pytest.mark.asyncio
async def test_tts_unconfigured_voice_and_unsupported_language():
    """Test unconfigured language voice never silently switches voices, and bad codes raise UnsupportedLanguageError."""
    tts = ElevenLabsTTSProvider(config=_make_voice_config(), client=_make_tts_client())

    # Tamil ('ta') has no voice_id configured in _make_voice_config()
    assert tts.supports_language("ta") is False
    res = await tts.synthesize("Test text", language_code="ta")
    assert res.success is False
    assert res.error_code == "VOICE_NOT_CONFIGURED"
    assert res.fallback_to_text is True

    with pytest.raises(UnsupportedLanguageError):
        await tts.synthesize("Bonjour", language_code="fr")


# =============================================================================
# 3. Missing API Key, Timeouts, Rate Limits, Quota, Invalid Audio & Empty Transcript
# =============================================================================


@pytest.mark.asyncio
async def test_missing_api_key_handled_safely():
    """Test missing ELEVENLABS_API_KEY fails safely with text fallback."""
    cfg = _make_voice_config(elevenlabs_api_key=None)
    stt = ElevenLabsSTTProvider(config=cfg)
    tts = ElevenLabsTTSProvider(config=cfg)

    stt_res = await stt.transcribe(_make_valid_wav(), language_code="en")
    tts_res = await tts.synthesize("Hello", language_code="en")

    assert stt_res.success is False and stt_res.error_code == "MISSING_API_KEY"
    assert tts_res.success is False and tts_res.error_code == "MISSING_API_KEY"


@pytest.mark.asyncio
async def test_provider_timeout_rate_limit_and_quota_errors(caplog):
    """Test STT/TTS timeouts, 429 rate limits, and 402 quota errors without exposing secrets."""
    secret_key = "SECRET-ELEVENLABS-KEY-DO-NOT-LOG"

    async def slow_stt(**kwargs):
        await asyncio.sleep(0.2)
        return SimpleNamespace(text="late")

    cfg = _make_voice_config(
        elevenlabs_api_key=secret_key,
        elevenlabs_timeout_seconds=0.02,
        elevenlabs_max_retries=2,
        elevenlabs_retry_base_delay_seconds=0.0,
    )
    stt_timeout = ElevenLabsSTTProvider(config=cfg, client=_make_stt_client(side_effect=slow_stt))
    res_to = await stt_timeout.transcribe(_make_valid_wav(), language_code="en")
    assert res_to.success is False
    assert res_to.error_code == "STT_TIMEOUT"
    assert res_to.fallback_to_text is True

    # 429 rate limit on STT
    rate_err = ApiError(status_code=429, body={"detail": "rate limit"})
    stt_rl = ElevenLabsSTTProvider(config=cfg, client=_make_stt_client(side_effect=rate_err))
    with caplog.at_level(logging.DEBUG):
        res_rl = await stt_rl.transcribe(_make_valid_wav(), language_code="en")
    assert res_rl.success is False
    assert res_rl.error_code == "RATE_LIMIT_EXCEEDED"
    assert secret_key not in caplog.text

    # 402 quota/plan error on TTS
    quota_err = ApiError(status_code=402, body={"detail": "paid_plan_required"})
    tts_quota = ElevenLabsTTSProvider(config=cfg, client=_make_tts_client(side_effect=quota_err))
    res_q = await tts_quota.synthesize("Hello", language_code="en")
    assert res_q.success is False
    assert res_q.error_code == "QUOTA_OR_PLAN_ERROR"
    assert res_q.fallback_to_text is True


@pytest.mark.asyncio
async def test_invalid_oversized_silent_audio_and_empty_transcription():
    """Test empty, invalid signature, oversized, silent audio, and empty STT transcript."""
    mock_client = _make_stt_client(SimpleNamespace(text="   ", language_code="eng", language_probability=0.5))
    cfg = _make_voice_config(max_audio_size_bytes=10000)
    stt = ElevenLabsSTTProvider(config=cfg, client=mock_client)

    # Empty audio
    r_empty = await stt.transcribe(b"", language_code="en")
    assert r_empty.success is False and r_empty.error_code == "EMPTY_AUDIO"

    # Invalid signature
    r_bad = await stt.transcribe(b"NOT_AUDIO_BYTES", language_code="en")
    assert r_bad.success is False and r_bad.error_code == "INVALID_AUDIO_SIGNATURE"

    # Oversized audio
    r_big = await stt.transcribe(b"RIFF" + b"\x00" * 11000, language_code="en")
    assert r_big.success is False and r_big.error_code == "AUDIO_TOO_LARGE"

    # Silent WAV
    r_silent = await stt.transcribe(_make_valid_wav(silent=True), language_code="en")
    assert r_silent.success is False and r_silent.error_code == "SILENT_OR_MALFORMED_AUDIO"

    # Empty transcript returned by STT
    r_blank = await stt.transcribe(_make_valid_wav(silent=False), language_code="en")
    assert r_blank.success is False and r_blank.error_code == "EMPTY_TRANSCRIPT"


# =============================================================================
# 4. Full VoiceAssistantPipeline: Consent Gates, Assistant Integration & Fallback
# =============================================================================


@pytest.mark.asyncio
async def test_pipeline_consent_denied_blocks_external_speech_calls():
    """Test external STT and TTS are never called when opt-in consent is denied or revoked."""
    stt_client = _make_stt_client(SimpleNamespace(text="hi", language_code="eng", language_probability=0.9))
    tts_client = _make_tts_client([b"audio"])
    cfg = _make_voice_config()

    gemini_client = MagicMock()
    gemini_client.aio.models.generate_content = AsyncMock(
        return_value=SimpleNamespace(
            text=json.dumps(
                {
                    "answer": "Hemoglobin is 13.5 g/dL.",
                    "documented_facts": ["Hemoglobin: 13.5 g/dL"],
                    "ai_observations": [],
                    "source_references": [
                        {"document_id": "doc-lab-1", "page_number": 1, "excerpt": "Hemoglobin: 13.5 g/dL"}
                    ],
                    "disclaimer": "Not a diagnosis.",
                    "confidence_score": 0.9,
                    "confidence_category": "high",
                }
            )
        )
    )
    gemini_cfg = AIProviderConfig(
        bridgecare_ai_provider="gemini",
        gemini_api_key="synthetic-gemini-key",
        gemini_model="gemini-3.5-flash-lite",
        gemini_max_retries=0,
    )
    assistant = MultilingualHealthAssistant(
        provider=GeminiProvider(config=gemini_cfg, client=gemini_client)
    )
    pipeline = VoiceAssistantPipeline(
        assistant=assistant,
        stt_provider=ElevenLabsSTTProvider(config=cfg, client=stt_client),
        tts_provider=ElevenLabsTTSProvider(config=cfg, client=tts_client),
    )

    # 1. STT consent denied -> blocks STT immediately
    turn_no_stt = await pipeline.handle_audio_turn(
        _make_valid_wav(),
        _sample_verified_records(),
        language_code="en",
        stt_consent_granted=False,
        tts_consent_granted=True,
        speak_response=True,
    )
    assert turn_no_stt.stt_result.success is False
    assert turn_no_stt.stt_result.error_code == "CONSENT_DENIED"
    assert turn_no_stt.assistant_response is None
    stt_client.speech_to_text.convert.assert_not_called()

    # 2. STT consent granted, TTS consent denied -> text response succeeds, TTS blocked
    turn_no_tts = await pipeline.handle_audio_turn(
        _make_valid_wav(),
        _sample_verified_records(),
        language_code="en",
        stt_consent_granted=True,
        tts_consent_granted=False,
        speak_response=True,
    )
    assert turn_no_tts.stt_result.success is True
    assert turn_no_tts.assistant_response is not None
    assert "13.5 g/dL" in turn_no_tts.assistant_response.answer
    assert turn_no_tts.tts_result is not None
    assert turn_no_tts.tts_result.success is False
    assert turn_no_tts.tts_result.error_code == "CONSENT_DENIED"
    assert turn_no_tts.tts_result.fallback_to_text is True


@pytest.mark.asyncio
async def test_pipeline_end_to_end_audio_to_assistant_to_tts_and_text_fallback():
    """Test complete Audio -> STT -> Assistant -> TTS flow and fallback when TTS is unavailable."""
    stt_client = _make_stt_client(
        SimpleNamespace(
            text="What is my Hemoglobin level?",
            language_code="eng",
            language_probability=0.97,
        )
    )
    tts_client = _make_tts_client([b"mp3-bytes-kannada"])
    cfg = _make_voice_config()

    gemini_client = MagicMock()
    gemini_client.aio.models.generate_content = AsyncMock(
        return_value=SimpleNamespace(
            text=json.dumps(
                {
                    "answer": "ನಿಮ್ಮ Hemoglobin 13.5 g/dL ಇದೆ.",
                    "documented_facts": ["Hemoglobin: 13.5 g/dL"],
                    "ai_observations": [],
                    "source_references": [
                        {"document_id": "doc-lab-1", "page_number": 1, "excerpt": "Hemoglobin: 13.5 g/dL"}
                    ],
                    "disclaimer": "ಇದು ವೈದ್ಯಕೀಯ ರೋಗನಿರ್ಣಯವಲ್ಲ.",
                    "confidence_score": 0.94,
                    "confidence_category": "high",
                }
            )
        )
    )
    gemini_cfg = AIProviderConfig(
        bridgecare_ai_provider="gemini",
        gemini_api_key="synthetic-gemini-key",
        gemini_model="gemini-3.5-flash-lite",
        gemini_max_retries=0,
    )
    assistant = MultilingualHealthAssistant(
        provider=GeminiProvider(config=gemini_cfg, client=gemini_client)
    )
    pipeline = VoiceAssistantPipeline(
        assistant=assistant,
        stt_provider=ElevenLabsSTTProvider(config=cfg, client=stt_client),
        tts_provider=ElevenLabsTTSProvider(config=cfg, client=tts_client),
    )

    turn = await pipeline.handle_audio_turn(
        _make_valid_wav(),
        _sample_verified_records(),
        language_code="kn",
        stt_consent_granted=True,
        tts_consent_granted=True,
        speak_response=True,
    )
    assert turn.stt_result.success is True
    assert turn.assistant_response.response_language == "kn"
    assert turn.assistant_response.is_clinical_diagnosis is False
    assert len(turn.assistant_response.source_references) == 1
    assert turn.tts_result.success is True
    assert turn.tts_result.audio_bytes == b"mp3-bytes-kannada"
    assert turn.tts_result.voice_id == "voice-kn-789"

    # External TTS unavailable (e.g. 503) -> text answer preserved as fallback
    err_tts = ElevenLabsTTSProvider(
        config=_make_voice_config(elevenlabs_max_retries=0),
        client=_make_tts_client(side_effect=ApiError(status_code=503, body={"detail": "unavailable"})),
    )
    fallback_pipeline = VoiceAssistantPipeline(
        assistant=assistant,
        stt_provider=ElevenLabsSTTProvider(config=cfg, client=stt_client),
        tts_provider=err_tts,
    )
    turn_fb = await fallback_pipeline.handle_audio_turn(
        _make_valid_wav(),
        _sample_verified_records(),
        language_code="kn",
        stt_consent_granted=True,
        tts_consent_granted=True,
        speak_response=True,
    )
    assert turn_fb.assistant_response is not None
    assert "13.5 g/dL" in turn_fb.assistant_response.answer
    assert turn_fb.tts_result.success is False
    assert turn_fb.tts_result.fallback_to_text is True


# =============================================================================
# 5. Remediation Tests: TTS Consent, Audio Validation, Grounding, Retention, etc.
# =============================================================================


@pytest.mark.asyncio
async def test_text_pipeline_tts_consent_defaults_to_false_and_opt_in_required():
    """Verify handle_text_with_optional_tts defaults tts_consent_granted=False and fails closed."""
    gemini_client = MagicMock()
    gemini_client.aio.models.generate_content = AsyncMock(
        return_value=SimpleNamespace(
            text=json.dumps(
                {
                    "answer": "Your Hemoglobin is 13.5 g/dL.",
                    "documented_facts": ["Hemoglobin: 13.5 g/dL"],
                    "ai_observations": [],
                    "source_references": [],
                    "disclaimer": "Not medical advice.",
                    "confidence_score": 0.95,
                    "confidence_category": "high",
                }
            )
        )
    )
    gemini_cfg = AIProviderConfig(
        bridgecare_ai_provider="gemini",
        gemini_api_key="synthetic-gemini-key",
        gemini_model="gemini-3.5-flash-lite",
        gemini_max_retries=0,
    )
    assistant = MultilingualHealthAssistant(
        provider=GeminiProvider(config=gemini_cfg, client=gemini_client)
    )
    tts_client = _make_tts_client([b"audio-bytes"])
    pipeline = VoiceAssistantPipeline(
        assistant=assistant,
        tts_provider=ElevenLabsTTSProvider(config=_make_voice_config(), client=tts_client),
    )

    # 1. speak_response=True with DEFAULT tts_consent_granted (must be False)
    turn_default = await pipeline.handle_text_with_optional_tts(
        question="What is my Hemoglobin?",
        verified_records=_sample_verified_records(),
        language_code="en",
        speak_response=True,
    )
    assert turn_default.assistant_response is not None
    assert turn_default.tts_result is not None
    assert turn_default.tts_result.success is False
    assert turn_default.tts_result.error_code == "CONSENT_DENIED"
    assert turn_default.tts_result.fallback_to_text is True
    tts_client.text_to_speech.convert.assert_not_called()

    # 2. speak_response=True with EXPLICIT tts_consent_granted=True
    turn_consented = await pipeline.handle_text_with_optional_tts(
        question="What is my Hemoglobin?",
        verified_records=_sample_verified_records(),
        language_code="en",
        speak_response=True,
        tts_consent_granted=True,
    )
    assert turn_consented.assistant_response is not None
    assert turn_consented.tts_result is not None
    assert turn_consented.tts_result.success is True
    assert turn_consented.tts_result.audio_bytes == b"audio-bytes"


def test_audio_validator_compressed_formats_and_mime_mismatch():
    """Verify audio validator handles compressed formats, metadata requirement, and MIME mismatch."""
    cfg = _make_voice_config(max_audio_duration_seconds=10.0)

    # 1. Magic byte signatures for all supported formats
    id3_mp3 = b"ID3\x03\x00\x00\x00\x00\x00#\x00" + b"\x00" * 20
    ogg = b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00" + b"\x00" * 20
    flac = b"fLaC\x00\x00\x00\x22" + b"\x00" * 34
    mp4 = b"\x00\x00\x00\x20ftypM4A \x00\x00\x00\x00" + b"\x00" * 20
    webm = b"\x1a\x45\xdf\xa3" + b"\x00" * 20

    # Non-WAV formats without duration metadata are rejected safely
    for fmt_bytes in (id3_mp3, ogg, flac, mp4, webm):
        res = validate_audio_bytes(fmt_bytes, config=cfg, duration_seconds=None)
        assert res.is_valid is False
        assert res.error_code == "DURATION_UNDETERMINED"

    # Non-WAV formats with valid duration metadata succeed
    res_mp3 = validate_audio_bytes(id3_mp3, config=cfg, duration_seconds=4.5)
    assert res_mp3.is_valid is True
    assert res_mp3.detected_mime_type == "audio/mpeg"
    assert res_mp3.duration_seconds == 4.5

    # Non-WAV formats with duration exceeding maximum are rejected
    res_oversized = validate_audio_bytes(id3_mp3, config=cfg, duration_seconds=15.0)
    assert res_oversized.is_valid is False
    assert res_oversized.error_code == "AUDIO_DURATION_EXCEEDED"

    # Declared vs detected MIME mismatch
    res_mismatch = validate_audio_bytes(
        _make_valid_wav(),
        config=cfg,
        declared_mime_type="audio/mp3",
    )
    assert res_mismatch.is_valid is False
    assert res_mismatch.error_code == "MIME_MISMATCH"

    # Compatible alias (audio/x-wav with WAV bytes, audio/mp3 with MP3 bytes) succeeds
    res_alias_wav = validate_audio_bytes(_make_valid_wav(), config=cfg, declared_mime_type="audio/x-wav")
    assert res_alias_wav.is_valid is True
    res_alias_mp3 = validate_audio_bytes(id3_mp3, config=cfg, declared_mime_type="audio/mp3", duration_seconds=3.0)
    assert res_alias_mp3.is_valid is True


def test_audio_validator_wav_silence_and_leading_silence():
    """Verify WAV validator detects silence across sample depths and does NOT reject leading silence."""
    # 1. WAV with 1.0 second leading silence followed by 0.5s speech is NOT rejected
    sample_rate = 16000
    silent_frames = int(1.0 * sample_rate)
    speech_frames = int(0.5 * sample_rate)
    bio = io.BytesIO()
    with wave.open(bio, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        raw_silent = struct.pack(f"<{silent_frames}h", *([0] * silent_frames))
        raw_speech = struct.pack(f"<{speech_frames}h", *([2500] * speech_frames))
        wf.writeframes(raw_silent + raw_speech)
    leading_silence_wav = bio.getvalue()

    res_leading = validate_audio_bytes(leading_silence_wav)
    assert res_leading.is_valid is True
    assert res_leading.duration_seconds == pytest.approx(1.5, rel=1e-2)

    # 2. Entirely silent 16-bit WAV is rejected
    res_silent = validate_audio_bytes(_make_valid_wav(duration_secs=0.5, silent=True))
    assert res_silent.is_valid is False
    assert res_silent.error_code == "SILENT_OR_MALFORMED_AUDIO"

    # 3. Entirely silent 8-bit unsigned PCM WAV is rejected
    bio8 = io.BytesIO()
    with wave.open(bio8, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(1)
        wf.setframerate(8000)
        wf.writeframes(bytes([128] * 1000))
    res_silent_8 = validate_audio_bytes(bio8.getvalue())
    assert res_silent_8.is_valid is False
    assert res_silent_8.error_code == "SILENT_OR_MALFORMED_AUDIO"


def test_medical_information_preservation_and_spoken_text_construction():
    """Verify construct_spoken_response_text preserves facts, disclaimers, and warnings without duplication."""
    base_response = AssistantChatResponse(
        answer="Your Hemoglobin is 13.5 g/dL and Metformin dosage is 500 mg daily.",
        response_language="en",
        response_language_name="English",
        disclaimer="This is an AI summary and not a clinical diagnosis.",
        documented_facts=["Hemoglobin: 13.5 g/dL", "Metformin: 500 mg daily"],
        conflicting_information=["Document A reports Metformin 500mg, but Document B reports 1000mg."],
        missing_information=["Missing recent HbA1c test result."],
        source_references=[],
        source_record_ids=["doc-lab-1"],
        confidence={"score": 0.92, "category": "high", "source": "gemini"},
        provider_used="gemini",
    )

    spoken = construct_spoken_response_text(base_response)
    # Facts and dosages preserved verbatim
    assert "Hemoglobin is 13.5 g/dL" in spoken
    assert "Metformin dosage is 500 mg daily" in spoken
    # Disclaimers and notices appended
    assert "This is an AI summary and not a clinical diagnosis." in spoken
    assert "Document A reports Metformin 500mg, but Document B reports 1000mg." in spoken
    assert "Missing recent HbA1c test result." in spoken

    # Warnings already included in answer are not duplicated
    response_with_inlined_warning = AssistantChatResponse(
        answer=(
            "Your Hemoglobin is 13.5 g/dL. This is an AI summary and not a clinical diagnosis. "
            "Note: Document A reports Metformin 500mg, but Document B reports 1000mg."
        ),
        response_language="en",
        response_language_name="English",
        disclaimer="This is an AI summary and not a clinical diagnosis.",
        conflicting_information=["Document A reports Metformin 500mg, but Document B reports 1000mg."],
        confidence={"score": 0.92, "category": "high", "source": "gemini"},
        provider_used="gemini",
    )
    spoken_dedup = construct_spoken_response_text(response_with_inlined_warning)
    assert spoken_dedup.count("This is an AI summary and not a clinical diagnosis.") == 1


@pytest.mark.asyncio
async def test_zero_retention_mode_configuration():
    """Verify enable_logging=False is passed to STT and TTS when Zero-Retention Mode is configured."""
    mock_stt = _make_stt_client(SimpleNamespace(text="Test speech", language_code="eng", language_probability=0.99))
    mock_tts = _make_tts_client([b"audio"])

    cfg_zr = _make_voice_config(elevenlabs_enable_logging=False)
    stt = ElevenLabsSTTProvider(config=cfg_zr, client=mock_stt)
    tts = ElevenLabsTTSProvider(config=cfg_zr, client=mock_tts)

    await stt.transcribe(_make_valid_wav(), language_code="en")
    assert mock_stt.speech_to_text.convert.call_args.kwargs.get("enable_logging") is False

    await tts.synthesize("Hello patient", language_code="en")
    assert mock_tts.text_to_speech.convert.call_args.kwargs.get("enable_logging") is False


@pytest.mark.asyncio
async def test_client_caching_and_lifecycle_cleanup():
    """Verify AsyncElevenLabs clients are cached, reused, and cleanly closed."""
    cfg = _make_voice_config(elevenlabs_api_key="real-dummy-key-for-cache-test")
    stt = ElevenLabsSTTProvider(config=cfg)
    tts = ElevenLabsTTSProvider(config=cfg)

    # First access creates client
    client1 = await stt._get_client()
    client2 = await stt._get_client()
    assert client1 is not None
    assert client1 is client2  # Reused instance

    client_tts1 = await tts._get_client()
    client_tts2 = await tts._get_client()
    assert client_tts1 is not None
    assert client_tts1 is client_tts2

    # Clean async cleanup
    await stt.aclose()
    assert stt._cached_client is None
    await tts.aclose()
    assert tts._cached_client is None


@pytest.mark.asyncio
async def test_tts_and_stt_model_compatibility():
    """Verify incompatible or unsupported models are rejected with explicit error codes."""
    # 1. eleven_v4_turbo on HTTP endpoint rejected
    cfg_turbo = _make_voice_config(elevenlabs_tts_model="eleven_v4_turbo")
    tts_turbo = ElevenLabsTTSProvider(config=cfg_turbo, client=_make_tts_client())
    res_turbo = await tts_turbo.synthesize("Test", language_code="en")
    assert res_turbo.success is False
    assert res_turbo.error_code == "INCOMPATIBLE_MODEL"
    assert "WebSocket" in res_turbo.error_message

    # 2. Unsupported TTS model
    cfg_bad_tts = _make_voice_config(elevenlabs_tts_model="invalid_model_xyz")
    tts_bad = ElevenLabsTTSProvider(config=cfg_bad_tts, client=_make_tts_client())
    res_bad = await tts_bad.synthesize("Test", language_code="en")
    assert res_bad.success is False
    assert res_bad.error_code == "UNSUPPORTED_TTS_MODEL"

    # 3. scribe_v2_medical on non-English rejected
    cfg_scribe_med = _make_voice_config(elevenlabs_stt_model="scribe_v2_medical")
    stt_med = ElevenLabsSTTProvider(config=cfg_scribe_med, client=_make_stt_client())
    res_med = await stt_med.transcribe(_make_valid_wav(), language_code="hi")
    assert res_med.success is False
    assert res_med.error_code == "UNSUPPORTED_LANGUAGE_FOR_MODEL"


@pytest.mark.asyncio
async def test_delegated_access_and_consent_grant_enforcement():
    """Verify VoiceAssistantPipeline enforces ConsentGrant authorization for delegated access."""
    gemini_client = MagicMock()
    gemini_client.aio.models.generate_content = AsyncMock(
        return_value=SimpleNamespace(
            text=json.dumps(
                {
                    "answer": "Patient Hemoglobin is 13.5 g/dL.",
                    "documented_facts": ["Hemoglobin: 13.5 g/dL"],
                    "ai_observations": [],
                    "source_references": [],
                    "disclaimer": "Not a diagnosis.",
                    "confidence_score": 0.9,
                    "confidence_category": "high",
                }
            )
        )
    )
    gemini_cfg = AIProviderConfig(
        bridgecare_ai_provider="gemini",
        gemini_api_key="synthetic-gemini-key",
        gemini_model="gemini-3.5-flash-lite",
        gemini_max_retries=0,
    )
    assistant = MultilingualHealthAssistant(
        provider=GeminiProvider(config=gemini_cfg, client=gemini_client)
    )
    pipeline = VoiceAssistantPipeline(assistant=assistant)

    records = _sample_verified_records()

    # 1. Delegated access without consent grant is denied
    turn_denied = await pipeline.handle_text_with_optional_tts(
        question="What is the hemoglobin level?",
        verified_records=records,
        language_code="en",
        patient_id="patient-100",
        recipient_id="caregiver-200",  # Different recipient -> delegated
    )
    assert turn_denied.delegated_access_authorized is False
    assert turn_denied.assistant_response is None
    assert turn_denied.delegated_access_denial_code == "AUTHORIZATION_UNAVAILABLE"

    # 2. Delegated access with active, valid consent grant is authorized
    active_grant = ConsentGrant(
        consent_id="grant-123",
        patient_id="patient-100",
        recipient_id="caregiver-200",
        purpose=SharingPurpose.CAREGIVER_VIEW,
        status=ConsentStatus.ACTIVE,
        permitted_document_ids=["doc-lab-1"],
        permitted_categories=[PermittedDataCategory.LAB_RESULTS],
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    turn_authorized = await pipeline.handle_text_with_optional_tts(
        question="What is the hemoglobin level?",
        verified_records=records,
        language_code="en",
        patient_id="patient-100",
        recipient_id="caregiver-200",
        sharing_purpose=SharingPurpose.CAREGIVER_VIEW,
        consent_grant=active_grant,
    )
    assert turn_authorized.delegated_access_authorized is True
    assert turn_authorized.assistant_response is not None
    assert "13.5 g/dL" in turn_authorized.assistant_response.answer

    # 3. Delegated access with revoked consent grant is denied
    revoked_grant = active_grant.model_copy(
        update={
            "status": ConsentStatus.REVOKED,
            "revoked_at": datetime.now(timezone.utc),
        }
    )
    turn_revoked = await pipeline.handle_text_with_optional_tts(
        question="What is the hemoglobin level?",
        verified_records=records,
        language_code="en",
        patient_id="patient-100",
        recipient_id="caregiver-200",
        sharing_purpose=SharingPurpose.CAREGIVER_VIEW,
        consent_grant=revoked_grant,
    )
    assert turn_revoked.delegated_access_authorized is False
    assert turn_revoked.assistant_response is None
    assert turn_revoked.delegated_access_denial_code == "CONSENT_REVOKED"


def test_capability_status_reports_both_providers():
    """Verify get_capability_status formats provider_name with both STT and TTS providers."""
    cfg = _make_voice_config()
    pipeline = VoiceAssistantPipeline(
        stt_provider=ElevenLabsSTTProvider(config=cfg),
        tts_provider=ElevenLabsTTSProvider(config=cfg),
    )
    status = pipeline.get_capability_status("en")
    assert "STT: ElevenLabsSTTProvider" in status.provider_name
    assert "TTS: ElevenLabsTTSProvider" in status.provider_name
