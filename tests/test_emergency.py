"""Emergency support tests."""

from __future__ import annotations


def _add_contact(client, patient, **overrides):
    payload = {
        "name": "Sister",
        "relationship": "sibling",
        "phone": "9999999999",
        "is_primary": True,
    }
    payload.update(overrides)
    return client.post(
        f"/api/v1/patients/{patient['profile_id']}/emergency/contacts",
        headers=patient["headers"],
        json=payload,
    )


def test_emergency_contact_crud(client, patient):
    created = _add_contact(client, patient)
    assert created.status_code == 201, created.text
    contact_id = created.json()["id"]

    listed = client.get(
        f"/api/v1/patients/{patient['profile_id']}/emergency/contacts",
        headers=patient["headers"],
    )
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "Sister"

    updated = client.patch(
        f"/api/v1/emergency/contacts/{contact_id}",
        headers=patient["headers"],
        json={"phone": "8888888888"},
    )
    assert updated.status_code == 200
    assert updated.json()["phone"] == "8888888888"

    deleted = client.delete(
        f"/api/v1/emergency/contacts/{contact_id}", headers=patient["headers"]
    )
    assert deleted.status_code == 200


def test_contact_cannot_be_modified_by_another_patient(client, patient, other_patient):
    contact_id = _add_contact(client, patient).json()["id"]
    response = client.patch(
        f"/api/v1/emergency/contacts/{contact_id}",
        headers=other_patient["headers"],
        json={"phone": "0000000000"},
    )
    assert response.status_code == 404


def test_emergency_summary_includes_only_verified_events(client, patient):
    client.patch(
        "/api/v1/patients/me",
        headers=patient["headers"],
        json={"allergy_summary": "Penicillin", "blood_group": "O+"},
    )
    unverified = client.post(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=patient["headers"],
        json={
            "category": "diagnosis",
            "title": "Unconfirmed finding",
            "recorded_at": "2025-01-01T00:00:00Z",
        },
    ).json()
    verified = client.post(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=patient["headers"],
        json={
            "category": "diagnosis",
            "title": "Confirmed asthma",
            "recorded_at": "2024-01-01T00:00:00Z",
        },
    ).json()
    client.post(
        f"/api/v1/records/{verified['id']}/verify",
        headers=patient["headers"],
        json={"status": "pending_review"},
    )
    client.post(
        f"/api/v1/records/{verified['id']}/verify",
        headers=patient["headers"],
        json={"status": "verified"},
    )
    _add_contact(client, patient)
    client.post(
        f"/api/v1/patients/{patient['profile_id']}/medications",
        headers=patient["headers"],
        json={
            "generic_name": "salbutamol",
            "active_ingredients": [{"name": "salbutamol", "strength": "100", "unit": "mcg"}],
            "started_on": "2024-02-01",
            "dose_text": "As prescribed",
        },
    )

    summary = client.get(
        f"/api/v1/patients/{patient['profile_id']}/emergency/summary",
        headers=patient["headers"],
    )
    assert summary.status_code == 200
    body = summary.json()
    assert body["patient"]["allergy_summary"] == "Penicillin"
    assert [event["title"] for event in body["recent_verified_events"]] == ["Confirmed asthma"]
    assert unverified["title"] not in str(body)
    assert body["active_medications"][0]["generic_name"] == "salbutamol"
    assert body["emergency_contacts"][0]["phone"] == "9999999999"
    assert "emergency care only" in body["disclosure_note"]


def test_emergency_summary_requires_emergency_scope(client, patient, other_patient):
    response = client.get(
        f"/api/v1/patients/{patient['profile_id']}/emergency/summary",
        headers=other_patient["headers"],
    )
    assert response.status_code == 404


def test_emergency_summary_access_is_audited(client, patient):
    client.get(
        f"/api/v1/patients/{patient['profile_id']}/emergency/summary",
        headers=patient["headers"],
    )
    audit = client.get(
        f"/api/v1/patients/{patient['profile_id']}/audit", headers=patient["headers"]
    ).json()
    assert any(
        entry["action"] == "emergency.summary_accessed" for entry in audit["items"]
    )


def test_hospital_directory_reports_it_is_not_configured(client, patient):
    response = client.get(
        "/api/v1/emergency/hospitals/nearby",
        headers=patient["headers"],
        params={"latitude": 19.076, "longitude": 72.8777, "radius_km": 5},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider_configured"] is False
    assert body["hospitals"] == []
    assert body["note"]
