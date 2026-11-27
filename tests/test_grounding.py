"""Deterministic tests for Medical Answer Grounding, Provenance, and Failure Scenarios."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_engine.assistant import MultilingualHealthAssistant
from ai_engine.providers import AIProviderConfig, GeminiProvider, UnverifiedRecordError
from ai_engine.schemas.common import ConfidenceCategory, VerificationStatus
from ai_engine.schemas.summary import SummaryResult
from ai_engine.timeline import LongitudinalTimelineBuilder


def _make_mock_client(response_text: str) -> MagicMock:
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(
        return_value=SimpleNamespace(text=response_text)
    )
    return client


def _make_provider(response_text: str = "{}") -> tuple[GeminiProvider, MagicMock]:
    mock_client = _make_mock_client(response_text)
    cfg = AIProviderConfig(
        bridgecare_ai_provider="gemini",
        gemini_api_key="synthetic-key",
        gemini_model="gemini-3.5-flash-lite",
        gemini_max_retries=0,
        gemini_retry_base_delay_seconds=0.0,
    )
    return GeminiProvider(config=cfg, client=mock_client), mock_client


@pytest.mark.asyncio
async def test_grounding_no_records_available():
    """Failure scenario: no records available returns insufficient_data without calling LLM."""
    provider, mock_client = _make_provider("{}")
    assistant = MultilingualHealthAssistant(provider=provider)

    resp = await assistant.ask("What is my Hemoglobin?", verified_records=[], language_code="en")
    assert resp.insufficient_data is True
    assert resp.documented_facts == []
    assert resp.is_clinical_diagnosis is False
    mock_client.aio.models.generate_content.assert_not_called()


@pytest.mark.asyncio
async def test_grounding_surfaces_missing_fields_and_conflicting_values_deterministically():
    """Failure scenarios: missing important fields and conflicting same-date values are always surfaced."""
    records = [
        {
            "document_id": "doc-1",
            "verification_status": "verified",
            "document_type": "lab_report",
            "document_date": "2026-03-01",
            "biomarkers": [
                {
                    "name": "TSH",
                    "value": "4.8",
                    "numeric_value": 4.8,
                    "unit": "mIU/L",
                    "source_reference": {"document_id": "doc-1", "page_number": 1, "excerpt": "TSH: 4.8 mIU/L"},
                }
            ],
            "missing_fields": ["doctor_name", "reference_range"],
        },
        {
            "document_id": "doc-2",
            "verification_status": "verified",
            "document_type": "lab_report",
            "document_date": "2026-03-01",
            "biomarkers": [
                {
                    "name": "TSH",
                    "value": "2.1",
                    "numeric_value": 2.1,
                    "unit": "mIU/L",
                    "source_reference": {"document_id": "doc-2", "page_number": 1, "excerpt": "TSH: 2.1 mIU/L"},
                }
            ],
        },
    ]
    # Even if model omits conflicting_information and missing_information, Assistant merges them deterministically
    llm_payload = json.dumps(
        {
            "answer": "Two verified reports from 2026-03-01 show conflicting TSH values (4.8 mIU/L and 2.1 mIU/L).",
            "documented_facts": ["TSH: 4.8 mIU/L (doc-1)", "TSH: 2.1 mIU/L (doc-2)"],
            "ai_observations": ["Conflicting same-date results require clinician review."],
            "source_references": [
                {"document_id": "doc-1", "page_number": 1, "excerpt": "TSH: 4.8 mIU/L"},
                {"document_id": "doc-2", "page_number": 1, "excerpt": "TSH: 2.1 mIU/L"},
            ],
            "missing_information": [],
            "conflicting_information": [],
            "uncertainty_flags": [],
            "disclaimer": "Not a clinical diagnosis.",
            "confidence_score": 0.65,
            "confidence_category": "medium",
        }
    )
    provider, _ = _make_provider(llm_payload)
    assistant = MultilingualHealthAssistant(provider=provider)

    resp = await assistant.ask("What is my TSH?", verified_records=records, language_code="en")
    assert len(resp.source_references) == 2
    assert any("Conflicting values recorded for 'TSH'" in c for c in resp.conflicting_information)
    assert "doctor_name" in resp.missing_information
    assert "reference_range" in resp.missing_information


@pytest.mark.asyncio
async def test_grounding_strips_wrong_page_number_and_missing_citation_flags():
    """Failure scenario: wrong page number or ungrounded excerpt is stripped and flagged."""
    records = [
        {
            "document_id": "doc-1",
            "verification_status": "verified",
            "document_type": "lab_report",
            "document_date": "2026-03-01",
            "biomarkers": [
                {
                    "name": "Hemoglobin",
                    "value": "13.5",
                    "numeric_value": 13.5,
                    "unit": "g/dL",
                    "source_reference": {"document_id": "doc-1", "page_number": 1, "excerpt": "Hemoglobin: 13.5 g/dL"},
                }
            ],
        }
    ]
    llm_payload = json.dumps(
        {
            "answer": "Hemoglobin is 13.5 g/dL.",
            "documented_facts": ["Hemoglobin: 13.5 g/dL"],
            "ai_observations": [],
            "source_references": [
                # Wrong page_number (page 5 instead of known page 1)
                {"document_id": "doc-1", "page_number": 5, "excerpt": "Hemoglobin: 13.5 g/dL"},
            ],
            "missing_information": [],
            "conflicting_information": [],
            "uncertainty_flags": [],
            "disclaimer": "Not a diagnosis.",
            "confidence_score": 0.85,
            "confidence_category": "high",
        }
    )
    provider, _ = _make_provider(llm_payload)
    assistant = MultilingualHealthAssistant(provider=provider)

    resp = await assistant.ask("What is my Hemoglobin?", verified_records=records, language_code="en")
    assert resp.source_references == []
    assert any("page 5" in u.reason for u in resp.uncertainty_flags)
    assert any(u.field_name == "source_references" for u in resp.uncertainty_flags)


@pytest.mark.asyncio
async def test_grounding_multiple_documents_supporting_one_claim():
    """Multiple documents supporting one claim retain all supporting SourceReferences."""
    records = [
        {
            "document_id": "doc-lab",
            "verification_status": "verified",
            "document_type": "lab_report",
            "document_date": "2026-03-01",
            "biomarkers": [
                {
                    "name": "Hemoglobin",
                    "value": "13.5",
                    "unit": "g/dL",
                    "source_reference": {"document_id": "doc-lab", "page_number": 1, "excerpt": "Hemoglobin: 13.5 g/dL"},
                }
            ],
        },
        {
            "document_id": "doc-discharge",
            "verification_status": "edited_verified",
            "document_type": "discharge_summary",
            "document_date": "2026-03-02",
            "clinical_events": [
                {
                    "event_type": "lab_review",
                    "description": "Hemoglobin noted at 13.5 g/dL.",
                    "source_reference": {"document_id": "doc-discharge", "page_number": 2, "excerpt": "Hemoglobin noted at 13.5 g/dL."},
                }
            ],
        },
    ]
    summary_payload = json.dumps(
        {
            "patient_friendly_summary": "Both your lab report and discharge summary record Hemoglobin 13.5 g/dL.",
            "doctor_ready_summary": "Hemoglobin 13.5 g/dL corroborated across doc-lab and doc-discharge.",
            "key_findings": ["Hemoglobin: 13.5 g/dL"],
            "source_references": [
                {"document_id": "doc-lab", "page_number": 1, "excerpt": "Hemoglobin: 13.5 g/dL"},
                {"document_id": "doc-discharge", "page_number": 2, "excerpt": "Hemoglobin noted at 13.5 g/dL."},
            ],
            "missing_information": [],
            "conflicting_information": [],
            "uncertainty_flags": [],
            "confidence_score": 0.95,
            "confidence_category": "high",
        }
    )
    provider, _ = _make_provider(summary_payload)
    raw = await provider.generate_summary(records, language_code="en")
    res = SummaryResult.model_validate(raw)

    assert {r.document_id for r in res.source_references} == {"doc-lab", "doc-discharge"}


@pytest.mark.asyncio
async def test_grounding_unrelated_and_unsupported_medical_questions():
    """Unrelated/unsupported questions return uncertain non-diagnostic responses without fabricated facts."""
    records = [
        {
            "document_id": "doc-1",
            "verification_status": "verified",
            "document_type": "lab_report",
            "document_date": "2026-03-01",
            "biomarkers": [{"name": "Hemoglobin", "value": "13.5", "unit": "g/dL"}],
        }
    ]
    payload = json.dumps(
        {
            "answer": "Your verified records only contain a Hemoglobin result (13.5 g/dL) and do not contain evidence to answer questions about changing medication or unrelated topics.",
            "documented_facts": [],
            "ai_observations": ["Insufficient evidence in supplied records for this question."],
            "source_references": [],
            "missing_information": ["No relevant clinical evidence for the requested topic."],
            "conflicting_information": [],
            "uncertainty_flags": [],
            "disclaimer": "Not a clinical diagnosis or treatment recommendation.",
            "confidence_score": 0.2,
            "confidence_category": "uncertain",
        }
    )
    provider, _ = _make_provider(payload)
    assistant = MultilingualHealthAssistant(provider=provider)

    resp = await assistant.ask(
        "Should I stop taking my heart medication?",
        verified_records=records,
        language_code="en",
    )
    assert resp.documented_facts == []
    assert resp.confidence.category == ConfidenceCategory.UNCERTAIN
    assert resp.is_clinical_diagnosis is False


@pytest.mark.asyncio
async def test_grounding_rejects_unverified_records_and_handles_duplicates():
    """Unverified records are rejected; duplicate records are flagged without losing provenance."""
    provider, _ = _make_provider("{}")
    assistant = MultilingualHealthAssistant(provider=provider)

    with pytest.raises(UnverifiedRecordError):
        await assistant.ask(
            "What is my Hemoglobin?",
            verified_records=[
                {"document_id": "u1", "verification_status": VerificationStatus.REJECTED.value}
            ],
        )

    builder = LongitudinalTimelineBuilder()
    dup_res = builder.build_from_records(
        [
            {
                "document_id": "dup-doc",
                "verification_status": "verified",
                "document_type": "lab_report",
                "document_date": "2026-03-01",
                "biomarkers": [{"name": "Hemoglobin", "value": "13.5", "unit": "g/dL"}],
            },
            {
                "document_id": "dup-doc",
                "verification_status": "verified",
                "document_type": "lab_report",
                "document_date": "2026-03-01",
                "biomarkers": [{"name": "Hemoglobin", "value": "13.5", "unit": "g/dL"}],
            },
        ]
    )
    assert any("Duplicate document_id" in u.reason for u in dup_res.uncertainty_flags)
