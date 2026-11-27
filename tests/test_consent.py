"""Consent, family and caregiver access tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.models.consent import ConsentGrant
from app.models.enums import ConsentStatus, FamilyRelationship
from app.models.patient import FamilyMember
from tests.conftest import make_account


def _grant(client, patient, grantee_email: str, scopes: list[str], **extra):
    payload = {
        "grantee_email": grantee_email,
        "scopes": scopes,
        "purpose": "care_coordination",
    }
    payload.update(extra)
    return client.post(
        f"/api/v1/patients/{patient['profile_id']}/consents",
        headers=patient["headers"],
        json=payload,
    )


def _accept(client, account, consent_id: str):
    return client.post(f"/api/v1/consents/{consent_id}/accept", headers=account["headers"])


def test_relationship_alone_never_grants_access(client, db_session, patient, other_patient):
    """A family link is metadata only; access still requires a grant."""
    db_session.add(
        FamilyMember(
            owner_user_id=uuid.UUID(patient["user_id"]),
            profile_id=uuid.UUID(other_patient["profile_id"]),
            relationship=FamilyRelationship.SPOUSE,
            is_dependent=False,
        )
    )
    db_session.flush()

    response = client.get(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=other_patient["headers"],
    )
    assert response.status_code == 404


def test_consent_requires_acceptance_before_access(client, patient, other_patient):
    created = _grant(client, patient, other_patient["email"], ["records"])
    assert created.status_code == 201, created.text
    consent = created.json()
    assert consent["status"] == "pending"

    denied = client.get(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=other_patient["headers"],
    )
    assert denied.status_code == 404

    pending = client.get("/api/v1/consents/pending", headers=other_patient["headers"])
    assert pending.status_code == 200
    assert pending.json()[0]["patient_display_name"] == "Asha Rao"

    accepted = _accept(client, other_patient, consent["id"])
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "active"

    allowed = client.get(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=other_patient["headers"],
    )
    assert allowed.status_code == 200


def test_consent_revocation_removes_access_immediately(client, patient, other_patient):
    consent = _grant(client, patient, other_patient["email"], ["records"]).json()
    _accept(client, other_patient, consent["id"])

    revoked = client.post(
        f"/api/v1/consents/{consent['id']}/revoke",
        headers=patient["headers"],
        json={"reason": "no longer needed"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    denied = client.get(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=other_patient["headers"],
    )
    assert denied.status_code == 404


def test_expired_consent_is_not_honoured(client, db_session, patient, other_patient):
    consent = _grant(client, patient, other_patient["email"], ["records"]).json()
    _accept(client, other_patient, consent["id"])

    grant = db_session.get(ConsentGrant, uuid.UUID(consent["id"]))
    grant.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()

    denied = client.get(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=other_patient["headers"],
    )
    assert denied.status_code == 404
    db_session.refresh(grant)
    assert grant.status == ConsentStatus.EXPIRED


def test_consent_expiry_must_be_in_the_future(client, patient, other_patient):
    response = _grant(
        client,
        patient,
        other_patient["email"],
        ["records"],
        expires_at=(datetime.now(UTC) - timedelta(hours=1)).isoformat(),
    )
    assert response.status_code == 422


def test_cannot_grant_consent_to_self(client, patient):
    response = _grant(client, patient, patient["email"], ["records"])
    assert response.status_code == 422


def test_unknown_grantee_is_rejected_not_silently_invited(client, patient):
    response = _grant(client, patient, "nobody@example.com", ["records"])
    assert response.status_code == 422
    assert "register" in response.json()["error"]["message"].lower()


def test_duplicate_active_grant_is_rejected(client, patient, other_patient):
    consent = _grant(client, patient, other_patient["email"], ["records"]).json()
    _accept(client, other_patient, consent["id"])
    duplicate = _grant(client, patient, other_patient["email"], ["medications"])
    assert duplicate.status_code == 409


def test_declined_invitation_grants_nothing(client, patient, other_patient):
    consent = _grant(client, patient, other_patient["email"], ["records"]).json()
    declined = client.post(
        f"/api/v1/consents/{consent['id']}/decline", headers=other_patient["headers"]
    )
    assert declined.status_code == 200
    assert declined.json()["status"] == "declined"

    denied = client.get(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=other_patient["headers"],
    )
    assert denied.status_code == 404


def test_grantee_can_self_revoke(client, patient, other_patient):
    consent = _grant(client, patient, other_patient["email"], ["records"]).json()
    _accept(client, other_patient, consent["id"])
    response = client.post(
        f"/api/v1/consents/{consent['id']}/revoke",
        headers=other_patient["headers"],
        json={"reason": "self revoke"},
    )
    assert response.status_code == 200
    assert response.json()["revoked_reason"] == "self revoke"


def test_consent_grants_are_read_only(client, patient, caregiver):
    """A caregiver with every scope still cannot write or verify."""
    write = client.post(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=caregiver["headers"],
        json={
            "category": "diagnosis",
            "title": "Caregiver edit",
            "recorded_at": "2025-01-01T00:00:00Z",
        },
    )
    assert write.status_code == 404

    measurement = client.post(
        f"/api/v1/patients/{patient['profile_id']}/biomarkers",
        headers=caregiver["headers"],
        json={
            "analyte_key": "hemoglobin",
            "analyte_display": "Hemoglobin",
            "value_numeric": "12.0",
            "unit": "g/dL",
            "collected_at": "2025-01-01T00:00:00Z",
        },
    )
    assert measurement.status_code == 404

    contact = client.post(
        f"/api/v1/patients/{patient['profile_id']}/emergency/contacts",
        headers=caregiver["headers"],
        json={"name": "Added by caregiver", "phone": "9000000000"},
    )
    assert contact.status_code == 404


def test_dependant_profile_is_reachable_only_by_guardian(client, patient, other_patient):
    created = client.post(
        "/api/v1/family/members",
        headers=patient["headers"],
        json={
            "display_name": "Minor Child",
            "relationship": "child",
            "date_of_birth": "2015-05-05",
            "guardianship_attested": True,
        },
    )
    assert created.status_code == 201, created.text
    member = created.json()
    dependant_id = member["profile"]["id"]

    family = client.get("/api/v1/family/members", headers=patient["headers"])
    assert family.status_code == 200
    assert family.json()[0]["relationship"] == "child"

    record = client.post(
        f"/api/v1/patients/{dependant_id}/records",
        headers=patient["headers"],
        json={
            "category": "vaccination",
            "title": "MMR booster",
            "recorded_at": "2025-04-01T00:00:00Z",
        },
    )
    assert record.status_code == 201

    denied = client.get(
        f"/api/v1/patients/{dependant_id}/records", headers=other_patient["headers"]
    )
    assert denied.status_code == 404


def test_family_link_requires_guardianship_attestation(client, patient):
    response = client.post(
        "/api/v1/family/members",
        headers=patient["headers"],
        json={
            "display_name": "Unattested Child",
            "relationship": "child",
            "guardianship_attested": False,
        },
    )
    assert response.status_code == 422


def test_removing_family_member_revokes_guardianship(client, patient):
    member = client.post(
        "/api/v1/family/members",
        headers=patient["headers"],
        json={
            "display_name": "Dependant",
            "relationship": "parent",
            "guardianship_attested": True,
        },
    ).json()
    dependant_id = member["profile"]["id"]

    removed = client.delete(
        f"/api/v1/family/members/{member['id']}", headers=patient["headers"]
    )
    assert removed.status_code == 200

    denied = client.get(
        f"/api/v1/patients/{dependant_id}/records", headers=patient["headers"]
    )
    assert denied.status_code == 404
