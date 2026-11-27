"""Automated tests for Milestone 3: Structured Medical Information Extraction."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from google.genai import errors as genai_errors
from pydantic import ValidationError
import pytest

from ai_engine.providers import (
    AIProviderConfig,
    GeminiProvider,
    MockProvider,
    ProviderAPIError,
    ProviderResponseError,
    ProviderTimeoutError,
    get_ai_provider,
)
from ai_engine.schemas.classification import DocumentType
from ai_engine.schemas.common import ConfidenceCategory
from ai_engine.schemas.extraction import ExtractionResult


def _make_mock_client(response_text: str | None = None, side_effect=None) -> MagicMock:
    """Create a mock google-genai Client with an async aio.models.generate_content method."""
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


# =============================================================================
# 1. Extraction Across All 7 Document Categories (Synthetic Fixtures)
# =============================================================================


@pytest.mark.asyncio
async def test_extract_lab_report_preserves_units_and_provenance():
    """Test lab_report extraction preserves exact values, original units, and SourceReference."""
    payload = json.dumps(
        {
            "document_date": "2026-02-15",
            "hospital_or_lab_name": "Synthetic Diagnostics Lab",
            "doctor_name": None,
            "patient_name": "Synthetic Patient A",
            "biomarkers": [
                {
                    "name": "Hemoglobin",
                    "value": "11.2",
                    "numeric_value": 11.2,
                    "unit": "g/dL",
                    "reference_range": "12.0-16.0",
                    "abnormal_flag": "LOW",
                    "confidence_score": 0.96,
                    "confidence_category": "high",
                    "source_reference": {
                        "page_number": 1,
                        "excerpt": "Hemoglobin: 11.2 g/dL (Ref: 12.0-16.0) LOW",
                        "field_name": "Hemoglobin",
                    },
                },
                {
                    "name": "Fasting Glucose",
                    "value": "94",
                    "numeric_value": 94.0,
                    "unit": "mg/dL",
                    "reference_range": "70-100",
                    "abnormal_flag": "NORMAL",
                    "confidence_score": 0.95,
                    "confidence_category": "high",
                    "source_reference": {
                        "page_number": 2,
                        "excerpt": "[Page 2] Fasting Glucose: 94 mg/dL",
                        "field_name": "Fasting Glucose",
                    },
                },
            ],
            "medications": [],
            "clinical_events": [],
            "missing_fields": ["doctor_name"],
            "uncertainty_flags": [],
            "overall_confidence_score": 0.95,
            "overall_confidence_category": "high",
        }
    )
    provider = GeminiProvider(config=_make_gemini_config(), client=_make_mock_client(payload))
    doc_text = (
        "[Page 1] Synthetic Diagnostics Lab | Date: 2026-02-15 | Patient: Synthetic Patient A\n"
        "Hemoglobin: 11.2 g/dL (Ref: 12.0-16.0) LOW\n"
        "[Page 2] Fasting Glucose: 94 mg/dL (Ref: 70-100)"
    )

    raw = await provider.extract_information(doc_text, DocumentType.LAB_REPORT.value)
    result = ExtractionResult.model_validate(raw)

    assert result.document_type == DocumentType.LAB_REPORT
    assert result.hospital_or_lab_name == "Synthetic Diagnostics Lab"
    assert result.patient_name == "Synthetic Patient A"
    assert result.doctor_name is None
    assert "doctor_name" in result.missing_fields
    assert len(result.biomarkers) == 2
    assert result.biomarkers[0].value == "11.2"
    assert result.biomarkers[0].unit == "g/dL"
    assert result.biomarkers[0].abnormal_flag == "LOW"
    assert result.biomarkers[0].source_reference.page_number == 1
    assert result.biomarkers[1].source_reference.page_number == 2
    assert result.medications == []
    assert result.overall_confidence.source == "gemini:gemini-3.5-flash-lite"


@pytest.mark.asyncio
async def test_extract_prescription():
    """Test prescription extraction captures explicit medication details without forcing biomarkers."""
    payload = json.dumps(
        {
            "document_date": "2026-03-01",
            "hospital_or_lab_name": "Synthetic City Clinic",
            "doctor_name": "Dr. Synthetic One",
            "patient_name": None,
            "biomarkers": [],
            "medications": [
                {
                    "brand_name": "ExampleMet",
                    "generic_ingredients": ["Metformin Hydrochloride"],
                    "strength": "500 mg",
                    "dosage": "1 tablet",
                    "frequency": "Twice daily",
                    "duration": "30 days",
                    "instructions": "Oral, take after meals",
                    "confidence_score": 0.93,
                    "confidence_category": "high",
                    "source_reference": {
                        "page_number": 1,
                        "excerpt": "ExampleMet (Metformin HCl) 500 mg - 1 tab twice daily x 30 days after meals",
                    },
                }
            ],
            "clinical_events": [],
            "missing_fields": ["patient_name"],
            "uncertainty_flags": [],
            "overall_confidence_score": 0.92,
            "overall_confidence_category": "high",
        }
    )
    provider = GeminiProvider(config=_make_gemini_config(), client=_make_mock_client(payload))
    raw = await provider.extract_information(
        "Synthetic City Clinic | Dr. Synthetic One | 2026-03-01\n"
        "Rx: ExampleMet (Metformin HCl) 500 mg - 1 tab twice daily x 30 days, oral after meals.",
        DocumentType.PRESCRIPTION.value,
    )
    result = ExtractionResult.model_validate(raw)

    assert result.document_type == DocumentType.PRESCRIPTION
    assert result.doctor_name == "Dr. Synthetic One"
    assert len(result.medications) == 1
    med = result.medications[0]
    assert med.brand_name == "ExampleMet"
    assert med.generic_ingredients == ["Metformin Hydrochloride"]
    assert med.strength == "500 mg"
    assert med.frequency == "Twice daily"
    assert med.duration == "30 days"
    assert med.instructions == "Oral, take after meals"
    assert result.biomarkers == []


@pytest.mark.asyncio
async def test_extract_discharge_summary():
    """Test discharge_summary extraction captures admission, diagnosis, discharge events and meds."""
    payload = json.dumps(
        {
            "document_date": "2026-01-14",
            "hospital_or_lab_name": "Synthetic General Hospital",
            "doctor_name": "Dr. Synthetic Attending",
            "patient_name": "Synthetic Patient B",
            "biomarkers": [],
            "medications": [
                {
                    "brand_name": None,
                    "generic_ingredients": ["Amoxicillin"],
                    "strength": "500 mg",
                    "dosage": "1 capsule",
                    "frequency": "Every 8 hours",
                    "duration": "5 days",
                    "instructions": "Complete full course",
                }
            ],
            "clinical_events": [
                {
                    "event_type": "admission",
                    "description": "Admitted for acute community-acquired bronchitis.",
                    "event_date": "2026-01-10",
                    "source_reference": {
                        "page_number": 1,
                        "excerpt": "Date of Admission: 2026-01-10. Diagnosis: Acute bronchitis.",
                    },
                },
                {
                    "event_type": "discharge",
                    "description": "Discharged in stable condition.",
                    "event_date": "2026-01-14",
                },
            ],
            "missing_fields": [],
            "uncertainty_flags": [],
            "overall_confidence_score": 0.91,
            "overall_confidence_category": "high",
        }
    )
    provider = GeminiProvider(config=_make_gemini_config(), client=_make_mock_client(payload))
    raw = await provider.extract_information(
        "Synthetic General Hospital Discharge Summary. Admitted 2026-01-10, Discharged 2026-01-14.",
        DocumentType.DISCHARGE_SUMMARY.value,
    )
    result = ExtractionResult.model_validate(raw)

    assert result.document_type == DocumentType.DISCHARGE_SUMMARY
    assert len(result.clinical_events) == 2
    assert result.clinical_events[0].event_type == "admission"
    assert result.clinical_events[1].event_type == "discharge"
    assert len(result.medications) == 1


@pytest.mark.asyncio
async def test_extract_clinical_note():
    """Test clinical_note extraction captures documented symptoms and diagnoses."""
    payload = json.dumps(
        {
            "document_date": "2026-04-05",
            "hospital_or_lab_name": "Synthetic Outpatient Center",
            "doctor_name": "Dr. Synthetic Consultant",
            "patient_name": None,
            "biomarkers": [],
            "medications": [],
            "clinical_events": [
                {
                    "event_type": "symptom",
                    "description": "Reported dry cough and mild fatigue for 4 days.",
                    "event_date": "2026-04-05",
                    "source_reference": {
                        "page_number": 1,
                        "excerpt": "Chief complaint: dry cough and mild fatigue x 4 days.",
                    },
                },
                {
                    "event_type": "diagnosis",
                    "description": "Viral upper respiratory tract infection.",
                    "event_date": "2026-04-05",
                },
            ],
            "missing_fields": ["patient_name"],
            "uncertainty_flags": [],
            "overall_confidence_score": 0.89,
            "overall_confidence_category": "high",
        }
    )
    provider = GeminiProvider(config=_make_gemini_config(), client=_make_mock_client(payload))
    raw = await provider.extract_information(
        "Consultation Note (2026-04-05): Chief complaint: dry cough and mild fatigue x 4 days. Assessment: Viral URI.",
        DocumentType.CLINICAL_NOTE.value,
    )
    result = ExtractionResult.model_validate(raw)

    assert result.document_type == DocumentType.CLINICAL_NOTE
    assert [e.event_type for e in result.clinical_events] == ["symptom", "diagnosis"]


@pytest.mark.asyncio
async def test_extract_ayush_record():
    """Test ayush_record extraction captures Ayurvedic formulation without forcing lab biomarkers."""
    payload = json.dumps(
        {
            "document_date": "2026-05-12",
            "hospital_or_lab_name": "Synthetic Ayurveda Kendra",
            "doctor_name": "Vaidya Synthetic",
            "patient_name": None,
            "biomarkers": [],
            "medications": [
                {
                    "brand_name": "Triphala Churna",
                    "generic_ingredients": ["Amalaki", "Bibhitaki", "Haritaki"],
                    "strength": None,
                    "dosage": "3 g",
                    "frequency": "Once at bedtime",
                    "duration": "14 days",
                    "instructions": "Take orally with lukewarm water",
                }
            ],
            "clinical_events": [
                {
                    "event_type": "symptom",
                    "description": "Mild indigestion reported.",
                    "event_date": "2026-05-12",
                }
            ],
            "missing_fields": ["patient_name", "strength"],
            "uncertainty_flags": [],
            "overall_confidence_score": 0.88,
            "overall_confidence_category": "high",
        }
    )
    provider = GeminiProvider(config=_make_gemini_config(), client=_make_mock_client(payload))
    raw = await provider.extract_information(
        "Synthetic Ayurveda Kendra | Vaidya Synthetic | Triphala Churna 3g at bedtime with lukewarm water x 14 days.",
        DocumentType.AYUSH_RECORD.value,
    )
    result = ExtractionResult.model_validate(raw)

    assert result.document_type == DocumentType.AYUSH_RECORD
    assert result.medications[0].brand_name == "Triphala Churna"
    assert result.medications[0].strength is None


@pytest.mark.asyncio
async def test_extract_insurance_doc():
    """Test insurance_doc extraction avoids forcing irrelevant clinical biomarkers/medications."""
    payload = json.dumps(
        {
            "document_date": "2026-06-01",
            "hospital_or_lab_name": "Synthetic Health Insurance Co.",
            "doctor_name": None,
            "patient_name": "Synthetic Insured",
            "biomarkers": [],
            "medications": [],
            "clinical_events": [
                {
                    "event_type": "insurance_preauthorization",
                    "description": "Pre-authorization approved for policy #SYN-7711.",
                    "event_date": "2026-06-01",
                }
            ],
            "missing_fields": [],
            "uncertainty_flags": [],
            "overall_confidence_score": 0.90,
            "overall_confidence_category": "high",
        }
    )
    provider = GeminiProvider(config=_make_gemini_config(), client=_make_mock_client(payload))
    raw = await provider.extract_information(
        "Synthetic Health Insurance Co. Pre-Authorization Approval for Policy #SYN-7711.",
        DocumentType.INSURANCE_DOC.value,
    )
    result = ExtractionResult.model_validate(raw)

    assert result.document_type == DocumentType.INSURANCE_DOC
    assert result.biomarkers == []
    assert result.medications == []
    assert result.clinical_events[0].event_type == "insurance_preauthorization"


@pytest.mark.asyncio
async def test_extract_other_document():
    """Test other document category extraction without forcing medical fields."""
    payload = json.dumps(
        {
            "document_date": None,
            "hospital_or_lab_name": "Synthetic Medical Center",
            "doctor_name": None,
            "patient_name": None,
            "biomarkers": [],
            "medications": [],
            "clinical_events": [],
            "missing_fields": ["document_date", "patient_name"],
            "uncertainty_flags": [
                {
                    "field_name": "document_type",
                    "reason": "Administrative receipt contains no clinical findings.",
                }
            ],
            "overall_confidence_score": 0.65,
            "overall_confidence_category": "medium",
        }
    )
    provider = GeminiProvider(config=_make_gemini_config(), client=_make_mock_client(payload))
    raw = await provider.extract_information(
        "Synthetic Medical Center Parking Receipt #00412 - Paid $5.00.",
        DocumentType.OTHER.value,
    )
    result = ExtractionResult.model_validate(raw)

    assert result.document_type == DocumentType.OTHER
    assert result.biomarkers == []
    assert result.medications == []
    assert result.clinical_events == []


# =============================================================================
# 2. Missing, Conflicting, Uncertain, and Missing-Source Edge Cases
# =============================================================================


@pytest.mark.asyncio
async def test_missing_values_are_preserved_as_none_and_listed():
    """Test missing fields are never invented and are tracked in missing_fields."""
    payload = json.dumps(
        {
            "document_date": None,
            "hospital_or_lab_name": None,
            "doctor_name": None,
            "patient_name": None,
            "biomarkers": [],
            "medications": [
                {
                    "brand_name": "SyntheticMed",
                    "generic_ingredients": [],
                    "strength": None,
                    "dosage": None,
                    "frequency": None,
                    "duration": None,
                    "instructions": None,
                }
            ],
            "clinical_events": [],
            "missing_fields": ["document_date", "doctor_name", "dosage", "frequency"],
            "uncertainty_flags": [
                {
                    "field_name": "dosage",
                    "reason": "Medication dosage and frequency were not recorded in the text.",
                }
            ],
            "overall_confidence_score": 0.45,
            "overall_confidence_category": "low",
        }
    )
    provider = GeminiProvider(config=_make_gemini_config(), client=_make_mock_client(payload))
    raw = await provider.extract_information(
        "Continue SyntheticMed as discussed.",
        DocumentType.PRESCRIPTION.value,
    )
    result = ExtractionResult.model_validate(raw)

    assert result.document_date is None
    assert result.medications[0].dosage is None
    assert result.medications[0].frequency is None
    assert "dosage" in result.missing_fields
    assert result.uncertainty_flags[0].field_name == "dosage"


@pytest.mark.asyncio
async def test_conflicting_values_reported_in_uncertainty_flags():
    """Test conflicting values in document text are flagged via FieldUncertainty."""
    payload = json.dumps(
        {
            "document_date": "2026-02-10",
            "hospital_or_lab_name": "Synthetic Lab",
            "doctor_name": None,
            "patient_name": None,
            "biomarkers": [
                {
                    "name": "TSH",
                    "value": "4.8",
                    "numeric_value": 4.8,
                    "unit": "mIU/L",
                    "confidence_score": 0.5,
                    "confidence_category": "uncertain",
                }
            ],
            "medications": [],
            "clinical_events": [],
            "missing_fields": [],
            "uncertainty_flags": [
                {
                    "field_name": "TSH",
                    "reason": "Conflicting TSH values reported: header table lists 4.8 mIU/L while summary note states 2.1 mIU/L.",
                    "source_reference": {
                        "page_number": 1,
                        "excerpt": "TSH: 4.8 mIU/L ... Note: repeat TSH 2.1 mIU/L",
                    },
                }
            ],
            "overall_confidence_score": 0.45,
            "overall_confidence_category": "uncertain",
        }
    )
    provider = GeminiProvider(config=_make_gemini_config(), client=_make_mock_client(payload))
    raw = await provider.extract_information(
        "Synthetic Lab (2026-02-10): TSH: 4.8 mIU/L. Summary Note: repeat TSH 2.1 mIU/L.",
        DocumentType.LAB_REPORT.value,
    )
    result = ExtractionResult.model_validate(raw)

    assert result.overall_confidence.category == ConfidenceCategory.UNCERTAIN
    assert len(result.uncertainty_flags) == 1
    assert "Conflicting TSH values" in result.uncertainty_flags[0].reason
    assert result.uncertainty_flags[0].source_reference is not None


@pytest.mark.asyncio
async def test_insufficient_text_returns_uncertain_extraction():
    """Test insufficient text returns uncertain ExtractionResult without calling Gemini."""
    mock_client = _make_mock_client("{}")
    provider = GeminiProvider(config=_make_gemini_config(), client=mock_client)

    with pytest.raises(ValidationError):
        await provider.extract_information("", DocumentType.LAB_REPORT.value)

    raw = await provider.extract_information("--- ?", DocumentType.LAB_REPORT.value)
    result = ExtractionResult.model_validate(raw)

    assert result.document_type == DocumentType.LAB_REPORT
    assert result.overall_confidence.category == ConfidenceCategory.UNCERTAIN
    assert "document_text" in result.missing_fields
    assert len(result.uncertainty_flags) == 1
    mock_client.aio.models.generate_content.assert_not_called()


@pytest.mark.asyncio
async def test_missing_source_reference_excerpt_handled_safely():
    """Test empty or missing source_reference excerpts do not crash SourceReference validation."""
    payload = json.dumps(
        {
            "document_date": "2026-02-01",
            "biomarkers": [
                {
                    "name": "Platelets",
                    "value": "210000",
                    "numeric_value": 210000.0,
                    "unit": "/uL",
                    "source_reference": {"page_number": 1, "excerpt": "   "},
                }
            ],
            "medications": [],
            "clinical_events": [],
            "missing_fields": [],
            "uncertainty_flags": [],
            "overall_confidence_score": 0.85,
            "overall_confidence_category": "high",
        }
    )
    provider = GeminiProvider(config=_make_gemini_config(), client=_make_mock_client(payload))
    raw = await provider.extract_information(
        "Synthetic CBC: Platelets 210000 /uL on 2026-02-01.",
        DocumentType.LAB_REPORT.value,
    )
    result = ExtractionResult.model_validate(raw)

    assert result.biomarkers[0].name == "Platelets"
    assert result.biomarkers[0].source_reference is None


# =============================================================================
# 3. Malformed JSON, Invalid Schemas, API Errors, Timeouts, Retries, Mock
# =============================================================================


@pytest.mark.asyncio
async def test_extraction_invalid_json_raises_response_error():
    """Test malformed JSON during extraction raises ProviderResponseError."""
    provider = GeminiProvider(
        config=_make_gemini_config(),
        client=_make_mock_client("{broken json"),
    )
    with pytest.raises(ProviderResponseError):
        await provider.extract_information(
            "Synthetic Lab Report: Hemoglobin 14.0 g/dL.",
            DocumentType.LAB_REPORT.value,
        )


@pytest.mark.asyncio
async def test_extraction_invalid_schema_raises_response_error():
    """Test schema-invalid model output (e.g. out-of-range confidence or wrong type) fails safely."""
    bad_payload = json.dumps(
        {
            "biomarkers": "not-a-list",
            "overall_confidence_score": 2.5,
        }
    )
    provider = GeminiProvider(
        config=_make_gemini_config(),
        client=_make_mock_client(bad_payload),
    )
    with pytest.raises(ProviderResponseError):
        await provider.extract_information(
            "Synthetic Lab Report: Hemoglobin 14.0 g/dL.",
            DocumentType.LAB_REPORT.value,
        )


@pytest.mark.asyncio
async def test_extraction_timeout_and_retry_limits():
    """Test extraction respects timeout and retry limits, raising ProviderTimeoutError."""
    async def slow_call(**kwargs):
        await asyncio.sleep(0.2)
        return SimpleNamespace(text="{}")

    mock_client = _make_mock_client(side_effect=slow_call)
    cfg = _make_gemini_config(
        gemini_timeout_seconds=0.02,
        gemini_max_retries=2,
        gemini_retry_base_delay_seconds=0.0,
    )
    provider = GeminiProvider(config=cfg, client=mock_client)

    with pytest.raises(ProviderTimeoutError):
        await provider.extract_information(
            "Synthetic Prescription: Tab Example 10mg daily.",
            DocumentType.PRESCRIPTION.value,
        )

    assert mock_client.aio.models.generate_content.call_count == 3


@pytest.mark.asyncio
async def test_extraction_api_error_never_falls_back_to_mock():
    """Test Gemini API failures during extraction raise ProviderAPIError and never fall back to mock."""
    secret_key = "SECRET-EXTRACTION-KEY-DO-NOT-EXPOSE"
    err = genai_errors.APIError(500, {"error": {"message": "Internal error"}})
    mock_client = _make_mock_client(side_effect=err)
    cfg = _make_gemini_config(
        gemini_api_key=secret_key,
        gemini_max_retries=1,
        gemini_retry_base_delay_seconds=0.0,
    )
    provider = GeminiProvider(config=cfg, client=mock_client)

    with pytest.raises(ProviderAPIError) as exc_info:
        await provider.extract_information(
            "Synthetic Clinical Note: Follow up in 2 weeks.",
            DocumentType.CLINICAL_NOTE.value,
        )

    assert exc_info.value.status_code == 500
    assert secret_key not in str(exc_info.value)
    assert mock_client.aio.models.generate_content.call_count == 2


@pytest.mark.asyncio
async def test_explicit_mock_provider_extraction_behaviour(monkeypatch):
    """Test explicit mock provider selection returns deterministic MockProvider extraction output."""
    monkeypatch.setenv("BRIDGECARE_AI_PROVIDER", "mock")
    provider = get_ai_provider(AIProviderConfig(_env_file=None))
    assert isinstance(provider, MockProvider)

    raw = await provider.extract_information(
        "Synthetic Lab Report: Hemoglobin 13.5 g/dL.",
        DocumentType.LAB_REPORT.value,
    )
    result = ExtractionResult.model_validate(raw)
    assert result.document_type == DocumentType.LAB_REPORT
    assert result.overall_confidence.source == "mock"
    assert "Extraction not implemented in mock provider" in result.missing_fields


# =============================================================================
# 4. Optional Live Gemini Integration Test (Synthetic Medical Text Only)
# =============================================================================


def _has_live_gemini_key() -> bool:
    cfg = AIProviderConfig()
    key = cfg.gemini_api_key.get_secret_value().strip() if cfg.gemini_api_key else ""
    return bool(key) and not key.startswith("synthetic-")


@pytest.mark.skipif(
    not _has_live_gemini_key(),
    reason="Live Gemini API key not configured; skipping live extraction test.",
)
@pytest.mark.asyncio
async def test_live_gemini_extraction_synthetic_lab_report():
    """Optional live integration test for GeminiProvider.extract_information using synthetic text."""
    cfg = AIProviderConfig(bridgecare_ai_provider="gemini")
    provider = get_ai_provider(cfg)
    assert isinstance(provider, GeminiProvider)

    synthetic_lab_report = (
        "[Page 1]\n"
        "SYNTHETIC DIAGNOSTIC LABORATORY\n"
        "Report Date: 2026-03-10\n"
        "Complete Blood Count (CBC)\n"
        "Hemoglobin: 13.8 g/dL (Reference Range: 12.0 - 16.0 g/dL)\n"
        "Platelet Count: 235,000 /uL (Reference Range: 150,000 - 450,000 /uL)\n"
    )
    raw = await provider.extract_information(synthetic_lab_report, DocumentType.LAB_REPORT.value)
    result = ExtractionResult.model_validate(raw)

    assert result.document_type == DocumentType.LAB_REPORT
    assert len(result.biomarkers) >= 2
    hb = next((b for b in result.biomarkers if "hemoglobin" in b.name.lower()), None)
    assert hb is not None
    assert "13.8" in hb.value
    assert hb.unit == "g/dL"
    assert result.overall_confidence.source.startswith("gemini:")
