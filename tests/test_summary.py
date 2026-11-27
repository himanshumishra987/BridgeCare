"""Automated tests for Milestone 4: Grounded Medical Summary Generation."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_engine.providers import (
    AIProviderConfig,
    GeminiProvider,
    MockProvider,
    ProviderResponseError,
    ProviderTimeoutError,
    UnverifiedRecordError,
    get_ai_provider,
)
from ai_engine.schemas.common import ConfidenceCategory, VerificationStatus
from ai_engine.schemas.summary import SummaryResult


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


def _sample_verified_lab_record(status: str = "verified", doc_id: str = "doc-syn-1") -> dict:
    return {
        "document_id": doc_id,
        "verification_status": status,
        "document_type": "lab_report",
        "document_date": "2026-03-01",
        "hospital_or_lab_name": "Synthetic Diagnostics Lab",
        "biomarkers": [
            {
                "name": "Hemoglobin",
                "value": "13.5",
                "numeric_value": 13.5,
                "unit": "g/dL",
                "reference_range": "12.0-16.0",
                "source_reference": {
                    "document_id": doc_id,
                    "page_number": 1,
                    "excerpt": "Hemoglobin: 13.5 g/dL",
                },
            }
        ],
        "medications": [],
        "clinical_events": [],
        "missing_fields": ["doctor_name"],
        "uncertainty_flags": [],
    }


@pytest.mark.asyncio
async def test_summary_valid_verified_records():
    """Test summary generation succeeds with explicitly verified records and preserves provenance."""
    payload = json.dumps(
        {
            "patient_friendly_summary": "Your synthetic lab report from 2026-03-01 shows Hemoglobin of 13.5 g/dL.",
            "doctor_ready_summary": "Lab Report (2026-03-01, Synthetic Diagnostics Lab): Hemoglobin 13.5 g/dL (Ref 12.0-16.0).",
            "key_findings": ["Hemoglobin: 13.5 g/dL (2026-03-01)"],
            "source_references": [
                {
                    "document_id": "doc-syn-1",
                    "page_number": 1,
                    "excerpt": "Hemoglobin: 13.5 g/dL",
                    "field_name": "Hemoglobin",
                }
            ],
            "missing_information": ["doctor_name"],
            "conflicting_information": [],
            "uncertainty_flags": [],
            "confidence_score": 0.94,
            "confidence_category": "high",
        }
    )
    provider = GeminiProvider(config=_make_gemini_config(), client=_make_mock_client(payload))
    raw = await provider.generate_summary([_sample_verified_lab_record(status="verified")])
    result = SummaryResult.model_validate(raw)

    assert result.insufficient_data is False
    assert result.is_clinically_verified is False
    assert result.provider_used == "gemini"
    assert result.is_mock is False
    assert result.source_record_ids == ["doc-syn-1"]
    assert len(result.source_references) == 1
    assert result.source_references[0].excerpt == "Hemoglobin: 13.5 g/dL"
    assert result.confidence.source == "gemini:gemini-3.5-flash-lite"


@pytest.mark.asyncio
async def test_summary_edited_and_verified_records_accepted():
    """Test records with verification_status='edited_verified' are accepted."""
    payload = json.dumps(
        {
            "patient_friendly_summary": "Edited and verified record shows Hemoglobin 13.5 g/dL.",
            "doctor_ready_summary": "Verified (edited) lab record: Hemoglobin 13.5 g/dL.",
            "key_findings": ["Hemoglobin: 13.5 g/dL"],
            "source_references": [],
            "missing_information": [],
            "conflicting_information": [],
            "uncertainty_flags": [],
            "confidence_score": 0.90,
            "confidence_category": "high",
        }
    )
    provider = GeminiProvider(config=_make_gemini_config(), client=_make_mock_client(payload))
    raw = await provider.generate_summary(
        [_sample_verified_lab_record(status=VerificationStatus.EDITED_VERIFIED.value)]
    )
    result = SummaryResult.model_validate(raw)

    assert result.insufficient_data is False
    assert "13.5 g/dL" in result.doctor_ready_summary


@pytest.mark.asyncio
async def test_summary_rejects_pending_review_records():
    """Test pending_review records are strictly rejected."""
    mock_client = _make_mock_client("{}")
    provider = GeminiProvider(config=_make_gemini_config(), client=mock_client)

    with pytest.raises(UnverifiedRecordError) as exc_info:
        await provider.generate_summary(
            [_sample_verified_lab_record(status=VerificationStatus.PENDING_REVIEW.value)]
        )

    assert exc_info.value.error_type == "UNVERIFIED_RECORD_ERROR"
    mock_client.aio.models.generate_content.assert_not_called()


@pytest.mark.asyncio
async def test_summary_rejects_rejected_and_unlabeled_records():
    """Test rejected records and records missing verification_status are safely rejected."""
    mock_client = _make_mock_client("{}")
    provider = GeminiProvider(config=_make_gemini_config(), client=mock_client)

    with pytest.raises(UnverifiedRecordError):
        await provider.generate_summary(
            [_sample_verified_lab_record(status=VerificationStatus.REJECTED.value)]
        )

    unlabeled = _sample_verified_lab_record()
    del unlabeled["verification_status"]
    with pytest.raises(UnverifiedRecordError):
        await provider.generate_summary([unlabeled])

    mock_client.aio.models.generate_content.assert_not_called()


@pytest.mark.asyncio
async def test_summary_empty_verified_records_returns_insufficient_data():
    """Test empty verified_records returns deterministic insufficient-data result without calling API."""
    mock_client = _make_mock_client("{}")
    provider = GeminiProvider(config=_make_gemini_config(), client=mock_client)

    raw = await provider.generate_summary([])
    result = SummaryResult.model_validate(raw)

    assert result.insufficient_data is True
    assert result.confidence.category == ConfidenceCategory.UNCERTAIN
    assert "Insufficient verified" in result.patient_friendly_summary
    mock_client.aio.models.generate_content.assert_not_called()


@pytest.mark.asyncio
async def test_summary_preserves_conflicting_records_and_missing_fields():
    """Test conflicting records and missing fields are surfaced explicitly."""
    rec1 = _sample_verified_lab_record(doc_id="doc-1")
    rec2 = {
        "document_id": "doc-2",
        "verification_status": "verified",
        "document_type": "prescription",
        "document_date": "2026-03-01",
        "medications": [{"brand_name": "ExampleMed", "dosage": "500 mg"}],
        "missing_fields": ["frequency", "duration"],
    }
    payload = json.dumps(
        {
            "patient_friendly_summary": "Records from 2026-03-01 show Hemoglobin 13.5 g/dL and ExampleMed 500 mg (frequency/duration missing).",
            "doctor_ready_summary": "Lab (doc-1) + Rx (doc-2): Conflict noted on patient address; Rx missing frequency/duration.",
            "key_findings": ["Hemoglobin 13.5 g/dL", "ExampleMed 500 mg"],
            "source_references": [],
            "missing_information": ["frequency", "duration"],
            "conflicting_information": ["Conflicting patient date of birth between doc-1 and doc-2."],
            "uncertainty_flags": [
                {"field_name": "frequency", "reason": "Dosing frequency not recorded."}
            ],
            "confidence_score": 0.72,
            "confidence_category": "medium",
        }
    )
    provider = GeminiProvider(config=_make_gemini_config(), client=_make_mock_client(payload))
    raw = await provider.generate_summary([rec1, rec2])
    result = SummaryResult.model_validate(raw)

    assert len(result.conflicting_information) == 1
    assert "frequency" in result.missing_information
    assert result.source_record_ids == ["doc-1", "doc-2"]


@pytest.mark.asyncio
async def test_summary_flags_unsupported_claims_and_fabricated_references():
    """Test unsupported document_id or fabricated excerpt in model output is flagged and stripped."""
    payload = json.dumps(
        {
            "patient_friendly_summary": "Summary of verified lab report.",
            "doctor_ready_summary": "Summary of verified lab report.",
            "key_findings": ["Hemoglobin 13.5 g/dL"],
            "source_references": [
                {
                    "document_id": "doc-hallucinated-999",
                    "page_number": 1,
                    "excerpt": "Hemoglobin: 13.5 g/dL",
                },
                {
                    "document_id": "doc-syn-1",
                    "page_number": 1,
                    "excerpt": "Fabricated diagnosis of diabetes not in record",
                },
                {
                    "document_id": "doc-syn-1",
                    "page_number": 1,
                    "excerpt": "Hemoglobin: 13.5 g/dL",
                },
            ],
            "missing_information": [],
            "conflicting_information": [],
            "uncertainty_flags": [],
            "confidence_score": 0.85,
            "confidence_category": "high",
        }
    )
    provider = GeminiProvider(config=_make_gemini_config(), client=_make_mock_client(payload))
    raw = await provider.generate_summary([_sample_verified_lab_record()])
    result = SummaryResult.model_validate(raw)

    # Only the 1 grounded reference survives
    assert len(result.source_references) == 1
    assert result.source_references[0].document_id == "doc-syn-1"
    # Both unsupported references are flagged in uncertainty_flags
    assert len(result.uncertainty_flags) == 2


@pytest.mark.asyncio
async def test_summary_invalid_json_and_invalid_pydantic_output():
    """Test malformed JSON and schema-invalid summary responses raise ProviderResponseError."""
    bad_json_provider = GeminiProvider(
        config=_make_gemini_config(),
        client=_make_mock_client("not-json"),
    )
    with pytest.raises(ProviderResponseError):
        await bad_json_provider.generate_summary([_sample_verified_lab_record()])

    bad_schema_provider = GeminiProvider(
        config=_make_gemini_config(),
        client=_make_mock_client(json.dumps({"patient_friendly_summary": ""})),
    )
    with pytest.raises(ProviderResponseError):
        await bad_schema_provider.generate_summary([_sample_verified_lab_record()])


@pytest.mark.asyncio
async def test_summary_api_timeout_and_retry_limits():
    """Test summary generation applies bounded timeouts and retry limits."""
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
        await provider.generate_summary([_sample_verified_lab_record()])

    assert mock_client.aio.models.generate_content.call_count == 3


@pytest.mark.asyncio
async def test_explicit_mock_provider_summary_behaviour(monkeypatch):
    """Test explicit mock provider selection returns deterministic MockProvider summary."""
    monkeypatch.setenv("BRIDGECARE_AI_PROVIDER", "mock")
    provider = get_ai_provider(AIProviderConfig(_env_file=None))
    assert isinstance(provider, MockProvider)

    res = await provider.generate_summary([_sample_verified_lab_record()])
    assert res["is_mock"] is True
    assert res["source"] == "mock"


def _has_live_gemini_key() -> bool:
    cfg = AIProviderConfig()
    key = cfg.gemini_api_key.get_secret_value().strip() if cfg.gemini_api_key else ""
    return bool(key) and not key.startswith("synthetic-")


@pytest.mark.skipif(
    not _has_live_gemini_key(),
    reason="Live Gemini API key not configured; skipping live summary test.",
)
@pytest.mark.asyncio
async def test_live_gemini_summary_synthetic_verified_records():
    """Optional live integration test for GeminiProvider.generate_summary using synthetic verified records."""
    cfg = AIProviderConfig(bridgecare_ai_provider="gemini")
    provider = get_ai_provider(cfg)
    assert isinstance(provider, GeminiProvider)

    raw = await provider.generate_summary([_sample_verified_lab_record(status="verified")])
    result = SummaryResult.model_validate(raw)

    assert result.insufficient_data is False
    assert result.is_clinically_verified is False
    assert result.provider_used == "gemini"
    assert "13.5" in result.doctor_ready_summary or "13.5" in result.patient_friendly_summary
