"""Insurance tests: coverage and claim status must never be overstated."""

from __future__ import annotations

from tests.conftest import make_account


def _add_policy(client, patient, **overrides):
    payload = {"policy_number": "POL-2025-0001", "policy_type": "health", "sum_insured": "500000"}
    payload.update(overrides)
    return client.post(
        f"/api/v1/patients/{patient['profile_id']}/insurance/policies",
        headers=patient["headers"],
        json=payload,
    )


def test_user_entered_coverage_is_not_described_as_confirmed(client, patient):
    response = _add_policy(client, patient)
    assert response.status_code == 201, response.text
    policy = response.json()
    assert policy["coverage_source"] == "user_entered"
    assert policy["coverage_confirmed"] is False
    assert "not been verified" in policy["coverage_note"]


def test_insurer_verified_coverage_requires_a_reference(client, patient):
    response = _add_policy(client, patient, coverage_source="insurer_verified")
    assert response.status_code == 422


def test_user_cannot_self_assert_insurer_verified_coverage(client, patient):
    """Only the insurer verification integration can produce INSURER_VERIFIED.

    Previously a client could pass ``coverage_source=insurer_verified`` with any
    reference string and be shown as confirmed. That is now refused: the value
    is not writable by users at all, even with a plausible reference.
    """
    response = _add_policy(
        client,
        patient,
        coverage_source="insurer_verified",
        verification_reference="INSURER-REF-7788",
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_claim_status_is_user_reported_until_verified(client, patient):
    created = client.post(
        f"/api/v1/patients/{patient['profile_id']}/insurance/claims",
        headers=patient["headers"],
        json={"claim_number": "CLM-1", "user_reported_status": "submitted"},
    )
    assert created.status_code == 201, created.text
    claim = created.json()
    assert claim["user_reported_status"] == "submitted"
    assert claim["status_is_insurer_verified"] is False
    assert "reported by the user" in claim["status_note"]
    assert claim["insurer_verified_status"] is None


def test_claim_update_records_the_time_and_cannot_fake_insurer_verification(client, patient):
    claim = client.post(
        f"/api/v1/patients/{patient['profile_id']}/insurance/claims",
        headers=patient["headers"],
        json={"claim_number": "CLM-2"},
    ).json()
    updated = client.patch(
        f"/api/v1/claims/{claim['id']}",
        headers=patient["headers"],
        json={"user_reported_status": "settled"},
    )
    assert updated.status_code == 200
    assert updated.json()["user_reported_status"] == "settled"
    assert updated.json()["user_status_updated_at"] is not None

    forged = client.patch(
        f"/api/v1/claims/{claim['id']}",
        headers=patient["headers"],
        json={"insurer_verified_status": "approved"},
    )
    assert forged.status_code == 422


def test_ayushman_card_number_is_masked(client, patient):
    created = client.post(
        f"/api/v1/patients/{patient['profile_id']}/insurance/ayushman-cards",
        headers=patient["headers"],
        json={"card_number": "12345678901234", "beneficiary_name": "Asha Rao"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["card_number_masked"] == "**********1234"
    assert "card_number" not in body

    listed = client.get(
        f"/api/v1/patients/{patient['profile_id']}/insurance/ayushman-cards",
        headers=patient["headers"],
    )
    assert listed.json()[0]["card_number_masked"].endswith("1234")


def test_hospitalisation_and_claim_documents(client, patient):
    hospitalisation = client.post(
        f"/api/v1/patients/{patient['profile_id']}/insurance/hospitalisations",
        headers=patient["headers"],
        json={
            "facility_name": "City General Hospital",
            "admission_date": "2025-03-01",
            "discharge_date": "2025-03-05",
            "total_amount": "45000",
        },
    )
    assert hospitalisation.status_code == 201, hospitalisation.text

    claim = client.post(
        f"/api/v1/patients/{patient['profile_id']}/insurance/claims",
        headers=patient["headers"],
        json={
            "claim_number": "CLM-3",
            "hospitalisation_id": hospitalisation.json()["id"],
        },
    ).json()

    upload = client.post(
        f"/api/v1/patients/{patient['profile_id']}/documents",
        headers=patient["headers"],
        files={"file": ("invoice.pdf", b"%PDF-1.4\ninvoice\n%%EOF\n", "application/pdf")},
    ).json()

    attached = client.post(
        f"/api/v1/claims/{claim['id']}/documents",
        headers=patient["headers"],
        json={"document_id": upload["id"], "kind": "invoice"},
    )
    assert attached.status_code == 201, attached.text

    duplicate = client.post(
        f"/api/v1/claims/{claim['id']}/documents",
        headers=patient["headers"],
        json={"document_id": upload["id"], "kind": "invoice"},
    )
    assert duplicate.status_code == 409

    listed = client.get(
        f"/api/v1/claims/{claim['id']}/documents", headers=patient["headers"]
    )
    assert len(listed.json()) == 1


def test_claim_cannot_reference_another_patients_policy(client, patient, other_patient):
    foreign_policy = _add_policy(client, other_patient).json()
    response = client.post(
        f"/api/v1/patients/{patient['profile_id']}/insurance/claims",
        headers=patient["headers"],
        json={"claim_number": "CLM-X", "policy_id": foreign_policy["id"]},
    )
    assert response.status_code == 422


def test_insurer_catalogue_is_admin_only(client, db_session, patient):
    from app.models.enums import UserRole
    from app.models.user import User
    import uuid

    created = client.post(
        "/api/v1/insurers",
        headers=patient["headers"],
        json={"name": "Example Health Insurance"},
    )
    assert created.status_code == 403

    admin = make_account(client, "catalogue.admin@example.com", "Catalogue Admin")
    user = db_session.get(User, uuid.UUID(admin["user_id"]))
    user.role = UserRole.ADMIN
    db_session.flush()

    allowed = client.post(
        "/api/v1/insurers",
        headers=admin["headers"],
        json={"name": "Example Health Insurance"},
    )
    assert allowed.status_code == 201, allowed.text
