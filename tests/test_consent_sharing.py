"""Automated tests for Consent-Aware Health Information Sharing."""

from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_engine.consent import (
    ConsentAuthorizationProvider,
    ConsentAwareSharingService,
    ConsentEnforcer,
)
from ai_engine.languages import LanguagePreference
from ai_engine.providers import AIProviderConfig, GeminiProvider
from ai_engine.schemas.consent import (
    ConsentGrant,
    ConsentQuestionRequest,
    ConsentShareRequest,
    ConsentStatus,
    PermittedDataCategory,
    SharingPurpose,
)


def _make_mock_client(response_text: str) -> MagicMock:
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(
        return_value=SimpleNamespace(text=response_text)
    )
    return client


def _make_gemini_provider(response_text: str = "{}") -> tuple[GeminiProvider, MagicMock]:
    mock_client = _make_mock_client(response_text)
    cfg = AIProviderConfig(
        bridgecare_ai_provider="gemini",
        gemini_api_key="synthetic-key",
        gemini_model="gemini-3.5-flash-lite",
        gemini_max_retries=0,
        gemini_retry_base_delay_seconds=0.0,
    )
    return GeminiProvider(config=cfg, client=mock_client), mock_client


def _active_grant(**overrides) -> ConsentGrant:
    defaults = {
        "consent_id": "consent-100",
        "patient_id": "patient-1",
        "recipient_id": "doctor-1",
        "purpose": SharingPurpose.CLINICAL_CONSULTATION,
        "status": ConsentStatus.ACTIVE,
        "permitted_document_ids": ["doc-lab-1"],
        "permitted_categories": [
            PermittedDataCategory.LAB_RESULTS,
            PermittedDataCategory.DOCUMENT_METADATA,
            PermittedDataCategory.SUMMARIES,
        ],
        "expires_at": datetime.now(timezone.utc) + timedelta(days=7),
    }
    defaults.update(overrides)
    return ConsentGrant(**defaults)


def _sample_records() -> list[dict]:
    return [
        {
            "document_id": "doc-lab-1",
            "patient_id": "patient-1",
            "verification_status": "verified",
            "document_type": "lab_report",
            "document_date": "2026-03-01",
            "hospital_or_lab_name": "Synthetic Lab",
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
            "medications": [
                {
                    "brand_name": "RestrictedMed",
                    "dosage": "10 mg",
                    "frequency": "Daily",
                }
            ],
            "clinical_events": [],
        },
        {
            "document_id": "doc-secret-2",
            "patient_id": "patient-1",
            "verification_status": "verified",
            "document_type": "clinical_note",
            "document_date": "2026-03-05",
            "biomarkers": [{"name": "UnauthorizedMarker", "value": "999", "unit": "U/L"}],
            "clinical_events": [{"event_type": "diagnosis", "description": "SECRET_DIAGNOSIS_DO_NOT_SHARE"}],
        },
        {
            "document_id": "doc-lab-1",
            "patient_id": "patient-1",
            "verification_status": "pending_review",
            "document_type": "lab_report",
            "biomarkers": [{"name": "UnverifiedMarker", "value": "55", "unit": "U/L"}],
        },
        {
            "document_id": "doc-other-patient",
            "patient_id": "patient-999",
            "verification_status": "verified",
            "document_type": "lab_report",
            "biomarkers": [{"name": "OtherPatientMarker", "value": "123", "unit": "U/L"}],
        },
    ]


@pytest.mark.asyncio
async def test_active_consent_filters_records_categories_and_preserves_provenance():
    """Test active consent shares only permitted docs/categories, preserves provenance, and prevents leaks."""
    summary_payload = json.dumps(
        {
            "patient_friendly_summary": "Verified Hemoglobin is 13.5 g/dL.",
            "doctor_ready_summary": "Lab (2026-03-01): Hemoglobin 13.5 g/dL.",
            "key_findings": ["Hemoglobin: 13.5 g/dL"],
            "source_references": [
                {"document_id": "doc-lab-1", "page_number": 1, "excerpt": "Hemoglobin: 13.5 g/dL"}
            ],
            "missing_information": [],
            "conflicting_information": [],
            "uncertainty_flags": [],
            "confidence_score": 0.94,
            "confidence_category": "high",
        }
    )
    provider, mock_client = _make_gemini_provider(summary_payload)
    service = ConsentAwareSharingService(provider=provider)

    req = ConsentShareRequest(
        patient_id="patient-1",
        recipient_id="doctor-1",
        purpose=SharingPurpose.CLINICAL_CONSULTATION,
        consent=_active_grant(),
        records=_sample_records(),
    )
    resp = await service.generate_shared_summary(req)

    assert resp.authorized is True
    assert resp.summary is not None
    assert resp.summary.is_clinically_verified is False
    assert len(resp.summary.source_references) == 1
    assert resp.summary.source_references[0].document_id == "doc-lab-1"

    # Audit metadata accurately reflects inclusion & exclusions without raw PHI
    assert resp.audit.decision == "allowed"
    assert resp.audit.included_document_ids == ["doc-lab-1"]
    assert resp.audit.excluded_record_count == 3

    # Verify unauthorized records & restricted categories NEVER entered the Gemini prompt
    sent_prompt = mock_client.aio.models.generate_content.call_args.kwargs["contents"]
    assert "Hemoglobin" in sent_prompt
    assert "RestrictedMed" not in sent_prompt
    assert "SECRET_DIAGNOSIS_DO_NOT_SHARE" not in sent_prompt
    assert "UnverifiedMarker" not in sent_prompt
    assert "OtherPatientMarker" not in sent_prompt


@pytest.mark.asyncio
async def test_missing_consent_and_unavailable_auth_service_denied_by_default():
    """Test missing consent and unavailable/failing backend auth service deny by default."""
    provider, mock_client = _make_gemini_provider("{}")

    # 1. No auth_provider and no explicit consent
    service_no_auth = ConsentAwareSharingService(provider=provider, auth_provider=None)
    resp1 = await service_no_auth.generate_shared_summary(
        ConsentShareRequest(
            patient_id="patient-1",
            recipient_id="doctor-1",
            purpose=SharingPurpose.CLINICAL_CONSULTATION,
            records=_sample_records(),
        )
    )
    assert resp1.authorized is False
    assert resp1.denial_code == "AUTHORIZATION_UNAVAILABLE"
    assert resp1.summary is None
    mock_client.aio.models.generate_content.assert_not_called()

    # 2. auth_provider returns None (missing consent)
    class NoneAuthProvider(ConsentAuthorizationProvider):
        async def get_authorization(self, patient_id, recipient_id, purpose, consent_id=None):
            return None

    service_none = ConsentAwareSharingService(provider=provider, auth_provider=NoneAuthProvider())
    resp2 = await service_none.generate_shared_summary(
        ConsentShareRequest(
            patient_id="patient-1",
            recipient_id="doctor-1",
            purpose=SharingPurpose.CLINICAL_CONSULTATION,
            records=_sample_records(),
        )
    )
    assert resp2.authorized is False
    assert resp2.denial_code == "CONSENT_MISSING"

    # 3. auth_provider raises exception (service unavailable)
    class FailingAuthProvider(ConsentAuthorizationProvider):
        async def get_authorization(self, patient_id, recipient_id, purpose, consent_id=None):
            raise ConnectionError("Backend auth service down")

    service_err = ConsentAwareSharingService(provider=provider, auth_provider=FailingAuthProvider())
    resp3 = await service_err.generate_shared_summary(
        ConsentShareRequest(
            patient_id="patient-1",
            recipient_id="doctor-1",
            purpose=SharingPurpose.CLINICAL_CONSULTATION,
            records=_sample_records(),
        )
    )
    assert resp3.authorized is False
    assert resp3.denial_code == "AUTHORIZATION_UNAVAILABLE"
    mock_client.aio.models.generate_content.assert_not_called()


@pytest.mark.asyncio
async def test_expired_and_revoked_consent_denied():
    """Test expired and revoked consents are strictly denied without invoking Gemini."""
    provider, mock_client = _make_gemini_provider("{}")
    service = ConsentAwareSharingService(provider=provider)

    # Expired by timestamp
    resp_exp = await service.generate_shared_summary(
        ConsentShareRequest(
            patient_id="patient-1",
            recipient_id="doctor-1",
            purpose=SharingPurpose.CLINICAL_CONSULTATION,
            consent=_active_grant(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)),
            records=_sample_records(),
        )
    )
    assert resp_exp.authorized is False
    assert resp_exp.denial_code == "CONSENT_EXPIRED"

    # Revoked by status / timestamp
    resp_rev = await service.generate_shared_summary(
        ConsentShareRequest(
            patient_id="patient-1",
            recipient_id="doctor-1",
            purpose=SharingPurpose.CLINICAL_CONSULTATION,
            consent=_active_grant(
                status=ConsentStatus.REVOKED,
                revoked_at=datetime.now(timezone.utc) - timedelta(hours=1),
            ),
            records=_sample_records(),
        )
    )
    assert resp_rev.authorized is False
    assert resp_rev.denial_code == "CONSENT_REVOKED"
    mock_client.aio.models.generate_content.assert_not_called()


@pytest.mark.asyncio
async def test_recipient_and_purpose_mismatch_denied():
    """Test recipient mismatch and purpose mismatch are denied."""
    provider, mock_client = _make_gemini_provider("{}")
    service = ConsentAwareSharingService(provider=provider)

    resp_rec = await service.generate_shared_summary(
        ConsentShareRequest(
            patient_id="patient-1",
            recipient_id="doctor-2-unauthorized",
            purpose=SharingPurpose.CLINICAL_CONSULTATION,
            consent=_active_grant(recipient_id="doctor-1"),
            records=_sample_records(),
        )
    )
    assert resp_rec.authorized is False
    assert resp_rec.denial_code == "RECIPIENT_MISMATCH"

    resp_purp = await service.generate_shared_summary(
        ConsentShareRequest(
            patient_id="patient-1",
            recipient_id="doctor-1",
            purpose=SharingPurpose.INSURANCE_CLAIM,
            consent=_active_grant(purpose=SharingPurpose.CLINICAL_CONSULTATION),
            records=_sample_records(),
        )
    )
    assert resp_purp.authorized is False
    assert resp_purp.denial_code == "PURPOSE_MISMATCH"
    mock_client.aio.models.generate_content.assert_not_called()


@pytest.mark.asyncio
async def test_restricted_categories_and_unverified_records_only_denied():
    """Test summary denied if SUMMARIES category absent, or if only unverified records exist."""
    provider, mock_client = _make_gemini_provider("{}")
    service = ConsentAwareSharingService(provider=provider)

    # 1. SUMMARIES category not granted
    no_sum_grant = _active_grant(permitted_categories=[PermittedDataCategory.LAB_RESULTS])
    resp_cat = await service.generate_shared_summary(
        ConsentShareRequest(
            patient_id="patient-1",
            recipient_id="doctor-1",
            purpose=SharingPurpose.CLINICAL_CONSULTATION,
            consent=no_sum_grant,
            records=_sample_records(),
        )
    )
    assert resp_cat.authorized is False
    assert resp_cat.denial_code == "CATEGORY_NOT_PERMITTED"

    # 2. Only unverified / rejected records supplied
    unverified_only = [
        {"document_id": "doc-lab-1", "verification_status": "pending_review", "biomarkers": [{"name": "Hb", "value": "12"}]},
        {"document_id": "doc-lab-1", "verification_status": "rejected", "biomarkers": [{"name": "Hb", "value": "12"}]},
    ]
    resp_unver = await service.generate_shared_summary(
        ConsentShareRequest(
            patient_id="patient-1",
            recipient_id="doctor-1",
            purpose=SharingPurpose.CLINICAL_CONSULTATION,
            consent=_active_grant(),
            records=unverified_only,
        )
    )
    assert resp_unver.authorized is False
    assert resp_unver.denial_code == "NO_AUTHORIZED_RECORDS"
    mock_client.aio.models.generate_content.assert_not_called()


@pytest.mark.asyncio
async def test_consent_aware_multilingual_qa_after_permission_filtering():
    """Test multilingual Q&A after consent filtering responds in selected language without leaking restricted data."""
    qa_payload = json.dumps(
        {
            "answer": "निष्कर्ष: Hemoglobin 13.5 g/dL है।",
            "documented_facts": ["Hemoglobin: 13.5 g/dL"],
            "ai_observations": [],
            "source_references": [
                {"document_id": "doc-lab-1", "page_number": 1, "excerpt": "Hemoglobin: 13.5 g/dL"}
            ],
            "missing_information": [],
            "conflicting_information": [],
            "uncertainty_flags": [],
            "disclaimer": "यह नैदानिक निदान नहीं है।",
            "confidence_score": 0.93,
            "confidence_category": "high",
        }
    )
    provider, mock_client = _make_gemini_provider(qa_payload)
    service = ConsentAwareSharingService(provider=provider)

    req = ConsentQuestionRequest(
        question="What are my lab results and medications?",
        patient_id="patient-1",
        recipient_id="doctor-1",
        purpose=SharingPurpose.CLINICAL_CONSULTATION,
        consent=_active_grant(),
        records=_sample_records(),
        language=LanguagePreference(language_code="hi", source_language="en"),
    )
    resp = await service.answer_shared_question(req)

    assert resp.authorized is True
    assert resp.response_language == "hi"
    assert resp.response_language_name == "Hindi"
    assert resp.assistant_response is not None
    assert resp.assistant_response.response_language == "hi"
    assert len(resp.assistant_response.source_references) == 1

    sent_prompt = mock_client.aio.models.generate_content.call_args.kwargs["contents"]
    assert "Response Language (MANDATORY): Hindi (hi)" in sent_prompt
    assert "RestrictedMed" not in sent_prompt
    assert "SECRET_DIAGNOSIS_DO_NOT_SHARE" not in sent_prompt
