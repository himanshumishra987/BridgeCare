"""AI context endpoint tests.

The assistant/summary feed may only ever contain records a human has verified,
and it carries the patient's saved language preference.
"""

from __future__ import annotations

import uuid

from app.core.config import get_settings
from tests.conftest import ai_headers


def _create_record(client, patient, title: str, recorded_at: str = "2025-03-04T08:30:00Z"):
    response = client.post(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=patient["headers"],
        json={
            "category": "lab_report",
            "title": title,
            "recorded_at": recorded_at,
            "summary": "Quarterly review",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _verify(client, patient, record_id: str) -> dict:
    url = f"/api/v1/records/{record_id}/verify"
    pending = client.post(
        url, headers=patient["headers"], json={"status": "pending_review"}
    )
    assert pending.status_code == 200, pending.text
    verified = client.post(
        url, headers=patient["headers"], json={"status": "verified", "note": "Checked"}
    )
    assert verified.status_code == 200, verified.text
    return verified.json()


def _context_url(patient) -> str:
    return f"/api/v1/internal/ai/patients/{patient['profile_id']}/context"


def test_context_returns_only_verified_records_with_saved_language(client, patient):
    verified = _verify(client, patient, _create_record(client, patient, "Verified panel")["id"])
    _create_record(client, patient, "Unverified draft")
    client.patch(
        "/api/v1/patients/me", headers=patient["headers"], json={"primary_language": "hi"}
    )

    response = client.get(_context_url(patient), headers=ai_headers())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["language"] == "hi"
    assert body["patient_id"] == patient["profile_id"]
    assert body["record_count"] == 1
    assert [record["id"] for record in body["records"]] == [verified["id"]]
    assert body["records"][0]["status"] == "verified"


def test_context_excludes_records_still_pending_review(client, patient):
    record = _create_record(client, patient, "Awaiting review")
    client.post(
        f"/api/v1/records/{record['id']}/verify",
        headers=patient["headers"],
        json={"status": "pending_review"},
    )

    response = client.get(_context_url(patient), headers=ai_headers())
    assert response.status_code == 200, response.text
    assert response.json()["records"] == []
    assert response.json()["record_count"] == 0


def test_context_requires_the_service_key(client, patient):
    assert client.get(_context_url(patient)).status_code == 401
    wrong = client.get(_context_url(patient), headers=ai_headers("wrong-key"))
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "not_authenticated"


def test_context_fails_closed_when_no_key_is_configured(client, patient, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_service_key", "")
    response = client.get(_context_url(patient), headers=ai_headers())
    assert response.status_code == 503


def test_context_rejects_unknown_patient(client):
    response = client.get(
        f"/api/v1/internal/ai/patients/{uuid.uuid4()}/context", headers=ai_headers()
    )
    assert response.status_code == 404


def test_context_fetch_is_audited_as_the_ai_service(client, patient):
    _verify(client, patient, _create_record(client, patient, "Verified panel")["id"])
    client.get(_context_url(patient), headers=ai_headers())

    audit = client.get(
        f"/api/v1/patients/{patient['profile_id']}/audit", headers=patient["headers"]
    ).json()
    entries = [item for item in audit["items"] if item["action"] == "ai.context_fetched"]
    assert entries
    assert entries[0]["actor_type"] == "ai_service"
    assert entries[0]["resource_type"] == "patient_profile"
    assert entries[0]["resource_id"] == patient["profile_id"]


def test_context_limit_is_bounded(client, patient):
    for value in ("0", "201"):
        response = client.get(
            f"{_context_url(patient)}?limit={value}", headers=ai_headers()
        )
        assert response.status_code == 422, response.text
