"""Patient isolation and IDOR tests.

Every cross-patient request must return 404 (never 403 with data, never 200),
so identifiers cannot be enumerated. Admin accounts get no implicit access.
"""

from __future__ import annotations

import uuid

from app.models.enums import UserRole
from app.models.user import User
from tests.conftest import MINIMAL_PDF, make_account


def _seed(client, patient: dict) -> dict[str, str]:
    headers = patient["headers"]
    pid = patient["profile_id"]

    record = client.post(
        f"/api/v1/patients/{pid}/records",
        headers=headers,
        json={
            "category": "lab_report",
            "title": "Complete blood count",
            "recorded_at": "2025-01-10T09:00:00Z",
            "summary": "Routine panel",
        },
    )
    assert record.status_code == 201, record.text

    measurement = client.post(
        f"/api/v1/patients/{pid}/biomarkers",
        headers=headers,
        json={
            "analyte_key": "hemoglobin",
            "analyte_display": "Hemoglobin",
            "value_numeric": "13.2",
            "unit": "g/dL",
            "collected_at": "2025-01-10T09:00:00Z",
        },
    )
    assert measurement.status_code == 201, measurement.text

    medication = client.post(
        f"/api/v1/patients/{pid}/medications",
        headers=headers,
        json={
            "brand_name": "Glucophage",
            "generic_name": "metformin",
            "active_ingredients": [{"name": "metformin", "strength": "500", "unit": "mg"}],
            "started_on": "2025-01-01",
        },
    )
    assert medication.status_code == 201, medication.text

    wellness = client.post(
        f"/api/v1/patients/{pid}/wellness",
        headers=headers,
        json={
            "care_system": "ayurveda",
            "record_type": "consultation",
            "title": "Ayurvedic consultation",
            "recorded_at": "2025-02-01T10:00:00Z",
            "herbs": [{"name": "Ashwagandha", "botanical_name": "Withania somnifera"}],
        },
    )
    assert wellness.status_code == 201, wellness.text

    contact = client.post(
        f"/api/v1/patients/{pid}/emergency/contacts",
        headers=headers,
        json={"name": "Sister", "phone": "9999999999", "relationship": "sibling"},
    )
    assert contact.status_code == 201, contact.text

    policy = client.post(
        f"/api/v1/patients/{pid}/insurance/policies",
        headers=headers,
        json={"policy_number": "POL-0001", "policy_type": "health"},
    )
    assert policy.status_code == 201, policy.text

    document = client.post(
        f"/api/v1/patients/{pid}/documents",
        headers=headers,
        files={"file": ("cbc.pdf", MINIMAL_PDF, "application/pdf")},
        data={"kind": "lab_report"},
    )
    assert document.status_code == 201, document.text

    return {
        "record": record.json()["id"],
        "measurement": measurement.json()["id"],
        "medication": medication.json()["id"],
        "wellness": wellness.json()["id"],
        "contact": contact.json()["id"],
        "policy": policy.json()["id"],
        "document": document.json()["id"],
    }


CROSS_PATIENT_REQUESTS = [
    ("get", "/patients/{pid}", None),
    ("get", "/patients/{pid}/records", None),
    ("get", "/records/{record}", None),
    ("patch", "/records/{record}", {"title": "Hijacked"}),
    ("post", "/records/{record}/verify", {"status": "verified"}),
    ("get", "/records/{record}/revisions", None),
    ("get", "/patients/{pid}/records/timeline", None),
    ("get", "/patients/{pid}/biomarkers", None),
    ("get", "/patients/{pid}/biomarkers/analytes", None),
    ("get", "/patients/{pid}/biomarkers/hemoglobin/trend", None),
    ("get", "/patients/{pid}/analytics/summary", None),
    ("get", "/patients/{pid}/medications", None),
    ("get", "/medications/{medication}", None),
    ("get", "/patients/{pid}/medications/checks/duplicate-ingredients", None),
    ("get", "/patients/{pid}/medications/checks/interaction-warnings", None),
    ("get", "/patients/{pid}/wellness", None),
    ("get", "/wellness/{wellness}", None),
    ("get", "/patients/{pid}/emergency/contacts", None),
    ("get", "/patients/{pid}/emergency/summary", None),
    ("get", "/patients/{pid}/insurance/policies", None),
    ("get", "/patients/{pid}/insurance/claims", None),
    ("get", "/patients/{pid}/audit", None),
    ("get", "/documents/{document}", None),
    ("get", "/documents/{document}/download", None),
    ("get", "/patients/{pid}/consents", None),
    ("get", "/patients/{pid}/documents", None),
]


def test_cross_patient_access_is_denied_everywhere(client, patient, other_patient):
    ids = _seed(client, patient)
    formatted = {**ids, "pid": patient["profile_id"]}

    for method, template, body in CROSS_PATIENT_REQUESTS:
        path = "/api/v1" + template.format(**formatted)
        kwargs: dict[str, object] = {"headers": other_patient["headers"]}
        if body is not None:
            kwargs["json"] = body
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 404, (method, path, response.status_code, response.text)
        assert response.json()["error"]["code"] == "not_found"


def test_owner_can_access_their_own_data(client, patient):
    ids = _seed(client, patient)
    response = client.get(
        f"/api/v1/records/{ids['record']}", headers=patient["headers"]
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Complete blood count"

    download = client.get(
        f"/api/v1/documents/{ids['document']}/download", headers=patient["headers"]
    )
    assert download.status_code == 200
    assert download.content.startswith(b"%PDF-")


def test_unknown_patient_id_returns_the_same_not_found(client, patient):
    response = client.get(
        f"/api/v1/patients/{uuid.uuid4()}", headers=patient["headers"]
    )
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Patient profile not found or not accessible."


def test_admin_has_no_implicit_access_to_health_records(client, db_session, patient):
    ids = _seed(client, patient)
    admin = make_account(client, "platform.admin@example.com", "Platform Admin")
    user = db_session.get(User, uuid.UUID(admin["user_id"]))
    assert user is not None
    user.role = UserRole.ADMIN
    db_session.flush()

    response = client.get(
        f"/api/v1/patients/{patient['profile_id']}", headers=admin["headers"]
    )
    assert response.status_code == 404

    record = client.get(f"/api/v1/records/{ids['record']}", headers=admin["headers"])
    assert record.status_code == 404


def test_denied_cross_patient_access_is_audited(client, patient, other_patient):
    _seed(client, patient)
    client.get(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=other_patient["headers"],
    )
    audit = client.get(
        f"/api/v1/patients/{patient['profile_id']}/audit", headers=patient["headers"]
    )
    assert audit.status_code == 200
    outcomes = [entry["outcome"] for entry in audit.json()["items"]]
    assert "denied" in outcomes


def test_patient_without_profile_scope_cannot_read_profile(client, patient, other_patient):
    """A grant covering only medications must not expose demographics or records."""
    granted = client.post(
        f"/api/v1/patients/{patient['profile_id']}/consents",
        headers=patient["headers"],
        json={
            "grantee_email": other_patient["email"],
            "scopes": ["medications"],
            "purpose": "medication_review",
        },
    )
    assert granted.status_code == 201, granted.text
    consent_id = granted.json()["id"]
    assert (
        client.post(
            f"/api/v1/consents/{consent_id}/accept", headers=other_patient["headers"]
        ).status_code
        == 200
    )

    records = client.get(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=other_patient["headers"],
    )
    assert records.status_code == 404

    profile = client.get(
        f"/api/v1/patients/{patient['profile_id']}", headers=other_patient["headers"]
    )
    assert profile.status_code == 404

    medications = client.get(
        f"/api/v1/patients/{patient['profile_id']}/medications",
        headers=other_patient["headers"],
    )
    assert medications.status_code == 200
