"""AI engine contract tests.

The AI engine may propose records; it may never assert clinical verification.
The service key is the only credential, and the contract rejects undocumented
fields so drift is caught immediately.
"""

from __future__ import annotations

from app.core.config import get_settings
from tests.conftest import MINIMAL_PDF, ai_headers

CONTRACT_VERSION = "2026-02-ai-contract-v1"


def _upload(client, patient, filename="hba1c.pdf"):
    response = client.post(
        f"/api/v1/patients/{patient['profile_id']}/documents",
        headers=patient["headers"],
        files={"file": (filename, MINIMAL_PDF, "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _envelope(patient, document_id, extraction_id="extract-0001", **overrides):
    payload = {
        "contract_version": CONTRACT_VERSION,
        "extraction_id": extraction_id,
        "document_id": document_id,
        "patient_id": patient["profile_id"],
        "engine_version": "gemini-1.5-pro",
        "received_at": "2025-05-01T10:00:00Z",
        "document_kind": "lab_report",
        "biomarkers": [
            {
                "analyte_key": "hba1c",
                "analyte_display": "HbA1c",
                "value_numeric": "6.4",
                "unit": "%",
                "collected_at": "2025-04-20T00:00:00Z",
                "ref_low": "4.0",
                "ref_high": "5.6",
                "source": {
                    "page": 1,
                    "char_start": 40,
                    "char_end": 60,
                    "confidence": 0.93,
                    "model_version": "gemini-1.5-pro",
                },
            }
        ],
        "medications": [
            {
                "generic_name": "metformin",
                "active_ingredients": [
                    {"name": "metformin", "strength": "500", "unit": "mg"}
                ],
                "started_on": "2025-01-01",
                "dose_text": "500 mg twice daily",
                "source": {"page": 1, "confidence": 0.88},
            }
        ],
        "clinical_events": [
            {
                "category": "lab_report",
                "title": "HbA1c panel",
                "summary": "Raised HbA1c noted",
                "recorded_at": "2025-04-20T00:00:00Z",
                "provider_name": "Sunrise Diagnostics",
                "source": {"page": 1, "confidence": 0.9},
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_service_key_is_required_and_compared(client, patient):
    document_id = _upload(client, patient)
    payload = _envelope(patient, document_id)

    assert client.post("/api/v1/internal/ai/extractions", json=payload).status_code == 401
    wrong = client.post(
        "/api/v1/internal/ai/extractions", json=payload, headers=ai_headers("wrong-key")
    )
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "not_authenticated"


def test_endpoints_fail_closed_when_no_key_is_configured(client, patient, monkeypatch):
    document_id = _upload(client, patient)
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_service_key", "")
    response = client.post(
        "/api/v1/internal/ai/extractions",
        json=_envelope(patient, document_id),
        headers=ai_headers(),
    )
    assert response.status_code == 503


def test_ingestion_creates_pending_review_records_with_provenance(client, patient):
    document_id = _upload(client, patient)
    response = client.post(
        "/api/v1/internal/ai/extractions",
        json=_envelope(patient, document_id),
        headers=ai_headers(),
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["created"] is True
    assert result["records_created"] == 1
    assert result["measurements_created"] == 1
    assert result["medications_created"] == 1
    assert result["verification_status"] == "pending_review"

    records = client.get(
        f"/api/v1/patients/{patient['profile_id']}/records", headers=patient["headers"]
    ).json()
    assert records["meta"]["total"] == 1
    record = records["items"][0]
    assert record["status"] == "pending_review"
    assert record["origin"] == "ai_engine"
    assert record["source_document_id"] == document_id
    assert record["provenance"]["page"] == 1
    assert record["provenance"]["confidence"] == 0.9

    measurements = client.get(
        f"/api/v1/patients/{patient['profile_id']}/biomarkers", headers=patient["headers"]
    ).json()
    assert measurements["meta"]["total"] == 1
    assert measurements["items"][0]["verification_status"] == "pending_review"

    medications = client.get(
        f"/api/v1/patients/{patient['profile_id']}/medications", headers=patient["headers"]
    ).json()
    assert medications["items"][0]["verification_status"] == "pending_review"

    document = client.get(f"/api/v1/documents/{document_id}", headers=patient["headers"])
    assert document.json()["status"] == "extracted"
    assert document.json()["kind"] == "lab_report"


def test_extraction_is_idempotent(client, patient):
    document_id = _upload(client, patient)
    payload = _envelope(patient, document_id)
    first = client.post(
        "/api/v1/internal/ai/extractions", json=payload, headers=ai_headers()
    )
    second = client.post(
        "/api/v1/internal/ai/extractions", json=payload, headers=ai_headers()
    )
    assert first.status_code == 200 and second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["records_created"] == 0

    records = client.get(
        f"/api/v1/patients/{patient['profile_id']}/records", headers=patient["headers"]
    ).json()
    assert records["meta"]["total"] == 1


def test_ai_cannot_mark_records_as_verified(client, patient):
    document_id = _upload(client, patient)
    response = client.post(
        "/api/v1/internal/ai/extractions",
        json=_envelope(patient, document_id, verification_status="verified"),
        headers=ai_headers(),
    )
    assert response.status_code == 422
    records = client.get(
        f"/api/v1/patients/{patient['profile_id']}/records", headers=patient["headers"]
    ).json()
    assert records["meta"]["total"] == 0


def test_contract_version_must_match(client, patient):
    document_id = _upload(client, patient)
    response = client.post(
        "/api/v1/internal/ai/extractions",
        json=_envelope(patient, document_id, contract_version="v0-unagreed"),
        headers=ai_headers(),
    )
    assert response.status_code == 422
    assert "contract version" in response.json()["error"]["message"].lower()


def test_undocumented_fields_are_rejected(client, patient):
    document_id = _upload(client, patient)
    payload = _envelope(patient, document_id)
    payload["summary_confidence"] = 0.77
    response = client.post(
        "/api/v1/internal/ai/extractions", json=payload, headers=ai_headers()
    )
    assert response.status_code == 422


def test_cannot_ingest_into_another_patients_document(client, patient, other_patient):
    foreign_document = _upload(client, other_patient, filename="other.pdf")
    response = client.post(
        "/api/v1/internal/ai/extractions",
        json=_envelope(patient, foreign_document),
        headers=ai_headers(),
    )
    assert response.status_code == 404


def test_document_content_fetch_is_audited(client, patient):
    document_id = _upload(client, patient)
    fetched = client.get(
        f"/api/v1/internal/ai/documents/{document_id}/content", headers=ai_headers()
    )
    assert fetched.status_code == 200
    assert fetched.content.startswith(b"%PDF-")
    assert fetched.headers["cache-control"] == "no-store"

    audit = client.get(
        f"/api/v1/patients/{patient['profile_id']}/audit", headers=patient["headers"]
    ).json()
    entries = [entry for entry in audit["items"] if entry["action"] == "ai.document_fetched"]
    assert entries
    assert entries[0]["actor_type"] == "ai_service"


def test_human_can_verify_an_ai_proposal(client, patient):
    document_id = _upload(client, patient)
    client.post(
        "/api/v1/internal/ai/extractions",
        json=_envelope(patient, document_id),
        headers=ai_headers(),
    )
    record = client.get(
        f"/api/v1/patients/{patient['profile_id']}/records", headers=patient["headers"]
    ).json()["items"][0]

    promoted = client.post(
        f"/api/v1/records/{record['id']}/verify",
        headers=patient["headers"],
        json={"status": "verified", "note": "Reviewed against the source PDF"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["status"] == "verified"
    assert promoted.json()["verified_by_user_id"] == patient["user_id"]
