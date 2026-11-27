"""Audit log tests: append-only, owner-only, and free of clinical content."""

from __future__ import annotations

import pytest

from app.db.base import utcnow
from app.models.audit import AuditLog, AuditLogImmutableError


def _new_entry(db_session) -> AuditLog:
    entry = AuditLog(action="test.event", occurred_at=utcnow(), context={"subject": "metadata"})
    db_session.add(entry)
    db_session.flush()
    return entry


def test_audit_rows_cannot_be_updated(db_session):
    entry = _new_entry(db_session)
    entry.action = "tampered"
    with pytest.raises(AuditLogImmutableError):
        db_session.flush()


def test_audit_rows_cannot_be_deleted(db_session):
    entry = _new_entry(db_session)
    db_session.delete(entry)
    with pytest.raises(AuditLogImmutableError):
        db_session.flush()


def test_audit_trail_is_restricted_to_the_record_owner(client, patient, caregiver):
    response = client.get(
        f"/api/v1/patients/{patient['profile_id']}/audit", headers=caregiver["headers"]
    )
    assert response.status_code == 404


def test_audit_trail_records_the_patients_own_actions(client, patient):
    client.post(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=patient["headers"],
        json={
            "category": "diagnosis",
            "title": "Asthma",
            "recorded_at": "2025-01-01T00:00:00Z",
        },
    )
    trail = client.get(
        f"/api/v1/patients/{patient['profile_id']}/audit", headers=patient["headers"]
    )
    assert trail.status_code == 200
    assert "record.created" in {entry["action"] for entry in trail.json()["items"]}

    # Reading the trail is itself audited, so the following read shows that access.
    again = client.get(
        f"/api/v1/patients/{patient['profile_id']}/audit", headers=patient["headers"]
    )
    assert "audit.viewed" in {entry["action"] for entry in again.json()["items"]}


def test_audit_never_stores_clinical_text(client, db_session, patient):
    secret = "Confidential oncology finding 42"
    client.post(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=patient["headers"],
        json={
            "category": "diagnosis",
            "title": "Consultation",
            "summary": secret,
            "recorded_at": "2025-01-01T00:00:00Z",
        },
    )
    trail = client.get(
        f"/api/v1/patients/{patient['profile_id']}/audit", headers=patient["headers"]
    )
    assert secret not in trail.text

    rows = db_session.query(AuditLog).all()
    assert rows
    persisted = " ".join(str(row.context) for row in rows)
    assert secret not in persisted


def test_audit_context_redacts_sensitive_keys(client, db_session, patient):
    from app.services.audit import record_audit

    record_audit(
        db_session,
        action="test.redaction",
        patient_id=None,
        context={"password": "hunter2", "notes": "free text", "scope": "records"},
    )
    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "test.redaction")
        .one()
    )
    assert entry.context["password"] == "[redacted]"
    assert entry.context["notes"] == "[redacted]"
    assert entry.context["scope"] == "records"
