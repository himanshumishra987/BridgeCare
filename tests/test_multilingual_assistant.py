"""Automated tests for BridgeCare Multilingual Conversational Health Assistant."""

import asyncio
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from PIL import Image
from pydantic import ValidationError
import pytest

from ai_engine.assistant import MultilingualHealthAssistant
from ai_engine.ingestion import DocumentIngestionEngine, check_ocr_language_support
from ai_engine.languages import (
    LANGUAGE_REGISTRY,
    LanguagePreference,
    SupportedLanguage,
    UnsupportedLanguageError,
    detect_source_language,
    validate_language_code,
)
from ai_engine.providers import (
    AIProviderConfig,
    GeminiProvider,
    MockProvider,
    ProviderAPIError,
    ProviderTimeoutError,
    UnverifiedRecordError,
    get_ai_provider,
)
from ai_engine.schemas.assistant import AssistantChatRequest, AssistantChatResponse
from ai_engine.schemas.common import VerificationStatus
from ai_engine.schemas.summary import SummaryResult
from ai_engine.voice import UnconfiguredSpeechProvider, VoiceAssistantPipeline


def _make_mock_client(response_text: str | None = None, side_effect=None) -> MagicMock:
    client = MagicMock()
    if side_effect is not None:
        client.aio.models.generate_content = AsyncMock(side_effect=side_effect)
    else:
        client.aio.models.generate_content = AsyncMock(
            return_value=SimpleNamespace(text=response_text)
        )
    return client


def _make_gemini_config(**overrides) -> AIProviderConfig:
    defaults = {
        "bridgecare_ai_provider": "gemini",
        "gemini_api_key": "synthetic-test-api-key-12345",
        "gemini_model": "gemini-3.5-flash-lite",
        "gemini_timeout_seconds": 5.0,
        "gemini_max_retries": 2,
        "gemini_retry_base_delay_seconds": 0.0,
    }
    defaults.update(overrides)
    return AIProviderConfig(**defaults)


def _sample_verified_records() -> list[dict]:
    return [
        {
            "document_id": "doc-lab-1",
            "verification_status": "verified",
            "document_type": "lab_report",
            "document_date": "2026-03-01",
            "hospital_or_lab_name": "Synthetic Diagnostics",
            "biomarkers": [
                {
                    "name": "Hemoglobin",
                    "value": "13.5",
                    "numeric_value": 13.5,
                    "unit": "g/dL",
                    "reference_range": "12.0-16.0",
                    "source_reference": {
                        "document_id": "doc-lab-1",
                        "page_number": 1,
                        "excerpt": "Hemoglobin: 13.5 g/dL",
                    },
                }
            ],
            "medications": [],
            "clinical_events": [],
            "missing_fields": ["doctor_name"],
        },
        {
            "document_id": "doc-rx-1",
            "verification_status": "edited_verified",
            "document_type": "prescription",
            "document_date": "2026-03-02",
            "medications": [
                {
                    "brand_name": "GlucoSyn",
                    "generic_ingredients": ["Metformin"],
                    "strength": "500 mg",
                    "dosage": "1 tablet",
                    "frequency": "Twice daily after meals",
                    "source_reference": {
                        "document_id": "doc-rx-1",
                        "page_number": 1,
                        "excerpt": "GlucoSyn (Metformin) 500 mg 1 tablet Twice daily after meals",
                    },
                }
            ],
            "biomarkers": [],
            "clinical_events": [],
        },
    ]


# =============================================================================
# 1. Language Registry & All 10 Supported Languages
# =============================================================================


@pytest.mark.parametrize("lang_enum", list(SupportedLanguage))
def test_all_ten_supported_language_codes(lang_enum: SupportedLanguage):
    """Test all 10 target language codes validate cleanly."""
    info = validate_language_code(lang_enum.value)
    assert info.code == lang_enum.value
    pref = LanguagePreference(language_code=lang_enum.value.upper())
    assert pref.language_code == lang_enum.value
    assert pref.response_language == lang_enum.value
    assert pref.language_name == LANGUAGE_REGISTRY[lang_enum.value].name


def test_unsupported_language_codes_rejected():
    """Test unsupported language codes raise UnsupportedLanguageError."""
    for bad_code in ("fr", "es", "xx", "", "   "):
        with pytest.raises(UnsupportedLanguageError):
            validate_language_code(bad_code)

        with pytest.raises(ValidationError) as exc_info:
            LanguagePreference(language_code=bad_code)
        assert "Unsupported language code" in str(exc_info.value)


# =============================================================================
# 2. Conversational Assistant: EN, HI, KN & Language Precedence
# =============================================================================


@pytest.mark.parametrize(
    "lang_code,question,expected_answer,expected_lang_name",
    [
        (
            "en",
            "What is my Hemoglobin level and medication dosage?",
            "Your verified lab report (2026-03-01) records Hemoglobin as 13.5 g/dL, and your prescription lists GlucoSyn (Metformin) 500 mg, 1 tablet Twice daily after meals.",
            "English",
        ),
        (
            "hi",
            "मेरा हीमोग्लोबिन स्तर और दवा की खुराक क्या है?",
            "आपकी सत्यापित रिपोर्ट (2026-03-01) में Hemoglobin 13.5 g/dL दर्ज है, और नुस्खे में GlucoSyn (Metformin) 500 mg, 1 tablet Twice daily after meals लिखा है।",
            "Hindi",
        ),
        (
            "kn",
            "ನನ್ನ ಹಿಮೋಗ್ಲೋಬಿನ್ ಮಟ್ಟ ಮತ್ತು ಔಷಧಿ ಪ್ರಮಾಣ ಎಷ್ಟು?",
            "ನಿಮ್ಮ ಪರಿಶೀಲಿಸಿದ ವರದಿಯಲ್ಲಿ (2026-03-01) Hemoglobin 13.5 g/dL ಎಂದು ದಾಖಲಾಗಿದೆ, ಮತ್ತು ಔಷಧಿ ಚೀಟಿಯಲ್ಲಿ GlucoSyn (Metformin) 500 mg, 1 tablet Twice daily after meals ಎಂದು ಇದೆ.",
            "Kannada",
        ),
    ],
)
@pytest.mark.asyncio
async def test_assistant_english_hindi_kannada_responses(
    lang_code: str,
    question: str,
    expected_answer: str,
    expected_lang_name: str,
):
    """Test EN, HI, and KN Q&A preserving exact values, units, medicine names, and source references."""
    payload = json.dumps(
        {
            "answer": expected_answer,
            "documented_facts": [
                "Hemoglobin: 13.5 g/dL (2026-03-01)",
                "GlucoSyn (Metformin) 500 mg - 1 tablet Twice daily after meals",
            ],
            "ai_observations": ["No clinical diagnosis is made."],
            "source_references": [
                {
                    "document_id": "doc-lab-1",
                    "page_number": 1,
                    "excerpt": "Hemoglobin: 13.5 g/dL",
                    "field_name": "Hemoglobin",
                }
            ],
            "missing_information": ["doctor_name"],
            "conflicting_information": [],
            "uncertainty_flags": [],
            "disclaimer": "Not a medical diagnosis.",
            "confidence_score": 0.94,
            "confidence_category": "high",
        }
    )
    mock_client = _make_mock_client(payload)
    provider = GeminiProvider(config=_make_gemini_config(), client=mock_client)
    assistant = MultilingualHealthAssistant(provider=provider)

    resp = await assistant.ask(
        question=question,
        verified_records=_sample_verified_records(),
        language_code=lang_code,
        source_language=lang_code,
    )
    assert isinstance(resp, AssistantChatResponse)
    assert resp.response_language == lang_code
    assert resp.response_language_name == expected_lang_name
    assert "13.5 g/dL" in resp.answer
    assert "GlucoSyn" in resp.answer
    assert "500 mg" in resp.answer
    assert len(resp.source_references) == 1
    assert resp.source_references[0].document_id == "doc-lab-1"
    assert resp.is_clinical_diagnosis is False
    assert resp.is_clinically_verified is False


@pytest.mark.asyncio
async def test_selected_language_takes_precedence_over_question_and_document_language():
    """Test Kannada selected + English question + English records -> responds in Kannada."""
    payload = json.dumps(
        {
            "answer": "ನಿಮ್ಮ ದಾಖಲೆಯಲ್ಲಿ Hemoglobin 13.5 g/dL ಇದೆ.",
            "documented_facts": ["Hemoglobin: 13.5 g/dL"],
            "ai_observations": [],
            "source_references": [
                {"document_id": "doc-lab-1", "page_number": 1, "excerpt": "Hemoglobin: 13.5 g/dL"}
            ],
            "missing_information": [],
            "conflicting_information": [],
            "uncertainty_flags": [],
            "disclaimer": "ಇದು ವೈದ್ಯಕೀಯ ರೋಗನಿರ್ಣಯವಲ್ಲ.",
            "confidence_score": 0.92,
            "confidence_category": "high",
        }
    )
    mock_client = _make_mock_client(payload)
    provider = GeminiProvider(config=_make_gemini_config(), client=mock_client)
    assistant = MultilingualHealthAssistant(provider=provider)

    resp = await assistant.ask(
        question="What is my Hemoglobin?",
        verified_records=_sample_verified_records(),
        language_code="kn",
        source_language="en",
    )
    assert resp.response_language == "kn"
    assert resp.response_language_name == "Kannada"
    assert resp.source_language == "en"
    # Verify prompt sent to Gemini explicitly mandated Kannada as Response Language
    sent_prompt = mock_client.aio.models.generate_content.call_args.kwargs["contents"]
    assert "Response Language (MANDATORY): Kannada (kn)" in sent_prompt


# =============================================================================
# 3. Multilingual Summaries Preserving Values, Units, Meds, Conflicts, Provenance
# =============================================================================


@pytest.mark.asyncio
async def test_translated_summary_preserves_values_units_meds_and_conflicts():
    """Test multilingual summary preserves exact biomarker values/units, meds, conflicts, and provenance."""
    records = _sample_verified_records() + [
        {
            "document_id": "doc-lab-2",
            "verification_status": "verified",
            "document_type": "lab_report",
            "document_date": "2026-03-01",
            "biomarkers": [
                {
                    "name": "Hemoglobin",
                    "value": "11.0",
                    "numeric_value": 11.0,
                    "unit": "g/dL",
                    "source_reference": {
                        "document_id": "doc-lab-2",
                        "page_number": 1,
                        "excerpt": "Hemoglobin: 11.0 g/dL",
                    },
                }
            ],
        }
    ]
    payload = json.dumps(
        {
            "patient_friendly_summary": "ತಮಿಳು/தமிழ் சுருக்கம்: Hemoglobin 13.5 g/dL மற்றும் 11.0 g/dL, GlucoSyn (Metformin) 500 mg Twice daily after meals.",
            "doctor_ready_summary": "தமிழ் மருத்துவ சுருக்கம்: Hemoglobin 13.5 g/dL vs 11.0 g/dL (2026-03-01); GlucoSyn 500 mg.",
            "key_findings": ["Hemoglobin: 13.5 g/dL", "GlucoSyn (Metformin) 500 mg"],
            "source_references": [
                {"document_id": "doc-lab-1", "page_number": 1, "excerpt": "Hemoglobin: 13.5 g/dL"},
                # Fabricated excerpt should be stripped and flagged
                {"document_id": "doc-lab-1", "page_number": 1, "excerpt": "Fabricated claim not in record"},
            ],
            "missing_information": ["doctor_name"],
            "conflicting_information": ["2026-03-01 Hemoglobin: 13.5 g/dL vs 11.0 g/dL"],
            "uncertainty_flags": [],
            "confidence_score": 0.85,
            "confidence_category": "medium",
        }
    )
    mock_client = _make_mock_client(payload)
    provider = GeminiProvider(config=_make_gemini_config(), client=mock_client)

    raw = await provider.generate_summary(records, language_code="ta")
    res = SummaryResult.model_validate(raw)

    assert res.response_language == "ta"
    assert res.response_language_name == "Tamil"
    assert "13.5 g/dL" in res.patient_friendly_summary
    assert "GlucoSyn (Metformin) 500 mg" in res.patient_friendly_summary
    assert len(res.conflicting_information) == 1
    assert "doctor_name" in res.missing_information
    # Only the grounded source reference survives; fabricated one is flagged
    assert len(res.source_references) == 1
    assert res.source_references[0].document_id == "doc-lab-1"
    assert len(res.uncertainty_flags) == 1


# =============================================================================
# 4. Safety, Empty Context, Unverified Records, OCR Limitations, Voice & Retries
# =============================================================================


@pytest.mark.asyncio
async def test_assistant_rejects_unverified_records_and_handles_empty_context():
    """Test pending_review/rejected records raise UnverifiedRecordError and empty context returns insufficient_data."""
    mock_client = _make_mock_client("{}")
    provider = GeminiProvider(config=_make_gemini_config(), client=mock_client)
    assistant = MultilingualHealthAssistant(provider=provider)

    # Empty medical context
    empty_resp = await assistant.ask("What is my blood sugar?", verified_records=[], language_code="hi")
    assert empty_resp.insufficient_data is True
    assert empty_resp.response_language == "hi"
    mock_client.aio.models.generate_content.assert_not_called()

    # Unverified record rejected
    with pytest.raises(UnverifiedRecordError):
        await assistant.ask(
            "What is my Hemoglobin?",
            verified_records=[
                {
                    "document_id": "pending-1",
                    "verification_status": VerificationStatus.PENDING_REVIEW.value,
                    "document_type": "lab_report",
                }
            ],
            language_code="en",
        )


@pytest.mark.asyncio
async def test_ocr_language_limitation_explicitly_reported():
    """Test requesting OCR for an uninstalled language pack reports the limitation instead of faking extraction."""
    supported, msg = check_ocr_language_support("kn")
    # On host with only 'eng' + 'osd' installed, 'kan' is unavailable
    if not supported:
        assert msg is not None
        assert "kan" in msg

        img = Image.new("RGB", (100, 50), color=(255, 255, 255))
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        engine = DocumentIngestionEngine()
        res = await engine.ingest_bytes(bio.getvalue(), original_filename="kn_scan.png", source_language="kn")
        assert res.success is False
        assert res.error_type == "EXTRACTION_FAILED"
        assert "kan" in res.pages[0].error_message


@pytest.mark.asyncio
async def test_assistant_provider_timeout_and_retry_without_mock_fallback():
    """Test timeout and API errors retry up to limit and raise without falling back to mock."""
    async def slow_call(**kwargs):
        await asyncio.sleep(0.2)
        return SimpleNamespace(text="{}")

    mock_client = _make_mock_client(side_effect=slow_call)
    cfg = _make_gemini_config(
        gemini_timeout_seconds=0.02,
        gemini_max_retries=2,
        gemini_retry_base_delay_seconds=0.0,
    )
    assistant = MultilingualHealthAssistant(provider=GeminiProvider(config=cfg, client=mock_client))

    with pytest.raises(ProviderTimeoutError):
        await assistant.ask("What is my Hemoglobin?", _sample_verified_records(), language_code="te")
    assert mock_client.aio.models.generate_content.call_count == 3


@pytest.mark.asyncio
async def test_voice_interface_reports_limitation_and_retains_text_interaction():
    """Test unconfigured speech provider reports limitation and keeps text interaction working."""
    mock_provider = MockProvider()
    assistant = MultilingualHealthAssistant(provider=mock_provider)
    voice_pipeline = VoiceAssistantPipeline(
        assistant=assistant,
        stt_provider=UnconfiguredSpeechProvider(),
        tts_provider=UnconfiguredSpeechProvider(),
    )

    turn = await voice_pipeline.handle_text_with_optional_tts(
        question="What is my Hemoglobin?",
        verified_records=_sample_verified_records(),
        language_code="kn",
        speak_response=True,
    )
    assert turn.assistant_response.response_language == "kn"
    assert turn.assistant_response.is_mock is True
    assert turn.voice_capability.fallback_to_text is True
    assert turn.tts_result is not None
    assert turn.tts_result.success is False
    assert turn.tts_result.fallback_to_text is True


# =============================================================================
# 5. Optional Live Gemini Multilingual Integration Tests
# =============================================================================


def _has_live_gemini_key() -> bool:
    cfg = AIProviderConfig()
    key = cfg.gemini_api_key.get_secret_value().strip() if cfg.gemini_api_key else ""
    return bool(key) and not key.startswith("synthetic-")


@pytest.mark.skipif(
    not _has_live_gemini_key(),
    reason="Live Gemini API key not configured; skipping live multilingual tests.",
)
@pytest.mark.asyncio
async def test_live_multilingual_assistant_kannada_precedence_and_hindi_summary():
    """Live Gemini test: Kannada selected + English question -> Kannada answer; Hindi summary."""
    cfg = AIProviderConfig(bridgecare_ai_provider="gemini")
    provider = get_ai_provider(cfg)
    assert isinstance(provider, GeminiProvider)
    assistant = MultilingualHealthAssistant(provider=provider)
    records = _sample_verified_records()

    # 1. Kannada selected, English question -> must respond in Kannada script/language
    qa_resp = await assistant.ask(
        question="What is my Hemoglobin level and what medicine is prescribed?",
        verified_records=records,
        language_code="kn",
        source_language="en",
    )
    assert qa_resp.response_language == "kn"
    assert "13.5" in qa_resp.answer
    assert any("\u0c80" <= ch <= "\u0cff" for ch in qa_resp.answer)  # Kannada Unicode block
    assert qa_resp.is_clinical_diagnosis is False

    # 2. Hindi summary preserving values & units
    hi_summary_raw = await provider.generate_summary(records, language_code="hi")
    hi_summary = SummaryResult.model_validate(hi_summary_raw)
    assert hi_summary.response_language == "hi"
    assert any("\u0900" <= ch <= "\u097f" for ch in hi_summary.patient_friendly_summary)  # Devanagari
    assert "13.5" in hi_summary.patient_friendly_summary


# =============================================================================
# 6. Automatic Language Detection, Mixed-Language, and Consistency Tests
# =============================================================================


@pytest.mark.parametrize(
    "sample_text,expected_code",
    [
        ("What is my hemoglobin level?", "en"),
        ("ನನ್ನ ಹಿಮೋಗ್ಲೋಬಿನ್ ಮಟ್ಟ ಎಷ್ಟು?", "kn"),
        ("என் ஹீமோகுளோபின் அளவு என்ன?", "ta"),
        ("నా హిమోగ్లోబిన్ స్థాయి ఎంత?", "te"),
        ("আমার হিমোগ্লোবিনের মাত্রা কত?", "bn"),
        ("મારું હિમોગ્લોબિન સ્તર કેટલું છે?", "gu"),
        ("എന്റെ ഹീമോഗ്ലോബിൻ അളവ് എത്രയാണ്?", "ml"),
        ("ମୋର ହିମୋଗ୍ଲୋବିନ୍ ସ୍ତର କେତେ?", "or"),
    ],
)
def test_automatic_source_language_detection_unambiguous_scripts(sample_text: str, expected_code: str):
    """Test deterministic script detection for unambiguous supported scripts."""
    res = detect_source_language(sample_text)
    assert res.detected_language == expected_code
    assert res.uncertain is False
    assert res.is_mixed_language is False


def test_automatic_detection_never_guesses_between_hindi_marathi_or_unsupported_scripts():
    """Test Devanagari (hi/mr), unsupported scripts, and numbers-only return uncertain=True."""
    dev_res = detect_source_language("मेरा हीमोग्लोबिन स्तर क्या है?")
    assert dev_res.detected_language is None
    assert dev_res.uncertain is True
    assert set(dev_res.candidate_languages) == {"hi", "mr"}

    cyrillic_res = detect_source_language("Какой у меня уровень гемоглобина?")
    assert cyrillic_res.detected_language is None
    assert cyrillic_res.uncertain is True

    num_res = detect_source_language("13.5 / 12.0 - 16.0")
    assert num_res.detected_language is None
    assert num_res.uncertain is True


@pytest.mark.asyncio
async def test_mixed_language_input_and_explicit_selection_precedence():
    """Test mixed-language question auto-detection preserves uncertainty while selected language wins."""
    payload = json.dumps(
        {
            "answer": "ನಿಮ್ಮ ದಾಖಲೆಯಲ್ಲಿ Hemoglobin 13.5 g/dL ಇದೆ.",
            "documented_facts": ["Hemoglobin: 13.5 g/dL"],
            "ai_observations": [],
            "source_references": [
                {"document_id": "doc-lab-1", "page_number": 1, "excerpt": "Hemoglobin: 13.5 g/dL"}
            ],
            "missing_information": [],
            "conflicting_information": [],
            "uncertainty_flags": [],
            "disclaimer": "ಇದು ವೈದ್ಯಕೀಯ ರೋಗನಿರ್ಣಯವಲ್ಲ.",
            "confidence_score": 0.91,
            "confidence_category": "high",
        }
    )
    mock_client = _make_mock_client(payload)
    assistant = MultilingualHealthAssistant(
        provider=GeminiProvider(config=_make_gemini_config(), client=mock_client)
    )

    # Mixed Devanagari + English question with explicit Kannada selected (no source_language passed)
    resp = await assistant.ask(
        question="मेरा Hemoglobin 13.5 g/dL ठीक है?",
        verified_records=_sample_verified_records(),
        language_code="kn",
        source_language=None,
    )
    assert resp.response_language == "kn"
    assert resp.response_language_name == "Kannada"
    assert resp.is_mixed_language is True
    assert any(u.field_name == "source_language" for u in resp.uncertainty_flags)


@pytest.mark.asyncio
async def test_mock_provider_summary_respects_language_metadata():
    """Test MockProvider.generate_summary returns consistent response_language metadata."""
    mock_provider = MockProvider()
    res = await mock_provider.generate_summary(_sample_verified_records(), language_code="gu")
    assert res["is_mock"] is True
    assert res["response_language"] == "gu"
    assert res["response_language_name"] == "Gujarati"


def test_english_ocr_pack_verified_available(monkeypatch):
    """Test that check_ocr_language_support verifies available packs and rejects missing ones."""
    monkeypatch.setattr("pytesseract.get_languages", lambda config="": ["eng", "osd"])
    supported_en, msg_en = check_ocr_language_support("en")
    assert supported_en is True
    assert msg_en is None

    supported_kn, msg_kn = check_ocr_language_support("kn")
    assert supported_kn is False
    assert msg_kn is not None and "kan" in msg_kn
