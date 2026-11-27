"""Insurance intelligence: policy documents, coverage facts, verification, guidance.

The scanner and the insurer verification provider are the deterministic ``stub``
adapters configured in ``conftest``. They are mocks of *external services*, not of
the backend logic under test: no real antivirus or insurer API is contacted, and
that distinction is called out wherever it matters.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.core.errors import ServiceUnavailableError
from app.models.enums import DocumentScanStatus
from app.models.insurance import (
    InsuranceCoverageFact,
    InsurerVerificationAttempt,
)
from tests.conftest import AI_SERVICE_KEY, MINIMAL_PDF, ai_headers, make_account

CONTRACT = "2026-11-insurance-contract-v1"


# --------------------------------------------------------------------------- helpers
def _create_policy(client, account, **overrides):
    payload = {
        "policy_number": "POL-2026-0001",
        "policy_type": "health",
        "sum_insured": "500000",
        "insurer_name_text": "Example Health Insurance",
        "valid_from": "2026-01-01",
        "valid_to": "2027-01-01",
    }
    payload.update(overrides)
    return client.post(
        f"/api/v1/patients/{account['profile_id']}/insurance/policies",
        headers=account["headers"],
        json=payload,
    )


def _policy(client, account, **overrides) -> dict:
    response = _create_policy(client, account, **overrides)
    assert response.status_code == 201, response.text
    return response.json()


def _upload(client, account, content: bytes = MINIMAL_PDF, name: str = "policy.pdf"):
    return client.post(
        f"/api/v1/patients/{account['profile_id']}/documents",
        headers=account["headers"],
        files={"file": (name, content, "application/pdf")},
        data={"kind": "insurance"},
    )


def _attach(client, account, policy_id: str, document_id: str, **overrides):
    payload = {"document_id": document_id, "role": "policy_copy"}
    payload.update(overrides)
    return client.post(
        f"/api/v1/insurance/policies/{policy_id}/documents",
        headers=account["headers"],
        json=payload,
    )


def _setup(client, account):
    policy = _policy(client, account)
    upload = _upload(client, account)
    assert upload.status_code == 201, upload.text
    document = upload.json()
    attached = _attach(client, account, policy["id"], document["id"])
    assert attached.status_code == 201, attached.text
    return policy, document


def _envelope(document: dict, account: dict, policy: dict, **overrides) -> dict:
    payload = {
        "contract_version": CONTRACT,
        "extraction_id": f"ins-{uuid.uuid4().hex[:12]}",
        "document_id": document["id"],
        "patient_id": account["profile_id"],
        "policy_id": policy["id"],
        "engine_version": "ai-engine-1.0",
        "received_at": "2026-03-01T10:00:00Z",
        "review_status": "needs_review",
        "coverage_facts": [
            {
                "field_key": "room_rent_limit",
                "value_numeric": "5000",
                "confidence": 0.92,
                "provenance": {
                    "page": 3,
                    "clause_reference": "4.2",
                    "snippet_sha256": "abcdef12",
                },
            }
        ],
    }
    payload.update(overrides)
    return payload


def _ingest(client, envelope: dict):
    return client.post(
        "/api/v1/internal/ai/insurance/extractions",
        headers=ai_headers(AI_SERVICE_KEY),
        json=envelope,
    )


# --------------------------------------------------------------------------- policy basics
def test_policy_detail_starts_empty_and_records_versions(client, patient):
    policy = _policy(client, patient)
    detail = client.get(f"/api/v1/insurance/policies/{policy['id']}", headers=patient["headers"])
    assert detail.status_code == 200, detail.text
    body = detail.json()
    # The policyholder is recorded as the primary insured member even for
    # individual cover, so a floater differs by *more members*, not by shape.
    assert len(body["insured_members"]) == 1
    assert body["insured_members"][0]["patient_id"] == patient["profile_id"]
    assert body["insured_members"][0]["is_primary"] is True
    assert body["documents"] == []
    assert body["coverage"]["facts"] == []
    assert body["coverage"]["coverage_confirmed"] is False
    assert [version["kind"] for version in body["versions"]] == ["created"]
    assert body["policy"]["version"] == 1

    updated = client.patch(
        f"/api/v1/insurance/policies/{policy['id']}",
        headers=patient["headers"],
        json={"sum_insured": "750000"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    versions = client.get(
        f"/api/v1/insurance/policies/{policy['id']}/versions", headers=patient["headers"]
    ).json()
    assert [version["kind"] for version in versions] == ["manual_update", "created"]


def test_family_floater_is_one_shared_policy_with_insured_members(client, patient):
    member = client.post(
        "/api/v1/family/members",
        headers=patient["headers"],
        json={
            "display_name": "Child Rao",
            "relationship": "child",
            "guardianship_attested": True,
        },
    )
    assert member.status_code == 201, member.text
    child_profile_id = member.json()["profile"]["id"]

    policy = _policy(
        client,
        patient,
        coverage_class="family_floater",
        insured_member_profile_ids=[child_profile_id],
    )
    assert policy["coverage_class"] == "family_floater"

    detail = client.get(f"/api/v1/insurance/policies/{policy['id']}", headers=patient["headers"]).json()
    assert detail["insured_members"]
    member_ids = {row["patient_id"] for row in detail["insured_members"]}
    assert member_ids == {patient["profile_id"], child_profile_id}
    primary = [row for row in detail["insured_members"] if row["is_primary"]]
    assert len(primary) == 1
    assert primary[0]["patient_id"] == patient["profile_id"]

    listed = client.get(
        f"/api/v1/patients/{patient['profile_id']}/insurance/policies",
        headers=patient["headers"],
    ).json()
    assert len(listed) == 1, "a floater must not be duplicated per member"


def test_insured_member_must_belong_to_the_policyholders_family(
    client, patient, other_patient
):
    policy = _policy(client, patient)
    foreign = client.post(
        f"/api/v1/insurance/policies/{policy['id']}/insured-members",
        headers=patient["headers"],
        json={"patient_id": other_patient["profile_id"], "relationship": "sibling"},
    )
    assert foreign.status_code == 422, foreign.text
    assert "guardian" in foreign.json()["error"]["message"]

    at_creation = _create_policy(
        client,
        patient,
        policy_number="POL-2026-0002",
        insured_member_profile_ids=[other_patient["profile_id"]],
    )
    assert at_creation.status_code == 422


def test_cross_patient_policy_access_is_denied(client, patient, other_patient):
    policy, document = _setup(client, patient)
    base = f"/api/v1/insurance/policies/{policy['id']}"
    requests = [
        ("get", base, None),
        ("get", f"{base}/coverage", None),
        ("get", f"{base}/guidance", None),
        ("get", f"{base}/versions", None),
        ("get", f"{base}/documents", None),
        ("get", f"{base}/extractions", None),
        ("patch", base, {"sum_insured": "1"}),
        ("post", f"{base}/archive", None),
        ("post", f"{base}/extract", {"document_id": document["id"]}),
        ("post", f"{base}/confirm", {}),
        ("post", f"{base}/coverage", {"field_key": "sum_insured", "value_numeric": "1"}),
        ("post", f"{base}/insured-members", {"patient_id": other_patient["profile_id"]}),
        ("post", f"{base}/verify", {"patient_authorization_reference": "AUTH-1"}),
    ]
    for method, path, body in requests:
        kwargs = {"headers": other_patient["headers"]}
        if body is not None:
            kwargs["json"] = body
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 404, (method, path, response.status_code, response.text)
        assert response.json()["error"]["code"] == "not_found"


def test_relationship_alone_does_not_grant_policy_access(client, patient):
    policy = _policy(client, patient)
    caregiver = make_account(client, "caregiver.inventory@example.com", "Care Giver")
    granted = client.post(
        f"/api/v1/patients/{patient['profile_id']}/consents",
        headers=patient["headers"],
        json={
            "grantee_email": caregiver["email"],
            "scopes": ["medications"],
            "purpose": "medication_review",
        },
    )
    assert granted.status_code == 201, granted.text
    accepted = client.post(
        f"/api/v1/consents/{granted.json()['id']}/accept", headers=caregiver["headers"]
    )
    assert accepted.status_code == 200

    denied = client.get(
        f"/api/v1/insurance/policies/{policy['id']}", headers=caregiver["headers"]
    )
    assert denied.status_code == 404


# --------------------------------------------------------------------------- documents & scanning
def test_duplicate_document_attachment_and_duplicate_extraction_are_idempotent(
    client, patient
):
    policy, document = _setup(client, patient)
    duplicate_attach = _attach(client, patient, policy["id"], document["id"])
    assert duplicate_attach.status_code == 409

    first = client.post(
        f"/api/v1/insurance/policies/{policy['id']}/extract",
        headers=patient["headers"],
        json={"document_id": document["id"]},
    )
    assert first.status_code == 202, first.text
    second = client.post(
        f"/api/v1/insurance/policies/{policy['id']}/extract",
        headers=patient["headers"],
        json={"document_id": document["id"]},
    )
    assert second.status_code == 202
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["status"] == "queued"


def test_infected_upload_is_rejected_and_never_listed(client, patient):
    # The stub scanner reports this marker as a positive verdict.
    response = _upload(client, patient, content=b"%PDF-1.4\nEICAR-TEST\n%%EOF\n", name="evil.pdf")
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "malware_detected"

    listed = client.get(
        f"/api/v1/patients/{patient['profile_id']}/documents", headers=patient["headers"]
    ).json()
    assert listed["items"] == []


def test_scanner_unavailable_never_means_clean(client, patient, db_session, monkeypatch):
    from app.models.document import Document
    from app.services import idta

    policy, document = _setup(client, patient)

    def _unavailable(_data: bytes):
        raise ServiceUnavailableError("No scanner configured.")

    # Force the stored document back to "never scanned" and make the scanner
    # unavailable, then try to process it.
    stored = db_session.get(Document, uuid.UUID(document["id"]))
    stored.scan_status = DocumentScanStatus.PENDING
    db_session.flush()
    monkeypatch.setattr(idta, "scan_bytes", _unavailable)

    scan = client.post(f"/api/v1/documents/{document['id']}/scan", headers=patient["headers"])
    assert scan.status_code == 503, scan.text

    extraction = client.post(
        f"/api/v1/insurance/policies/{policy['id']}/extract",
        headers=patient["headers"],
        json={"document_id": document["id"]},
    )
    # The failed scan is recorded as ``error``, and an error is never clean: the
    # extraction is refused with 503 rather than proceeding on an unknown file.
    assert extraction.status_code == 503
    assert extraction.json()["error"]["code"] == "service_unavailable"


def test_extraction_requires_a_clean_scan_verdict(client, patient, db_session):
    from app.models.document import Document

    policy, document = _setup(client, patient)
    stored = db_session.get(Document, uuid.UUID(document["id"]))
    stored.scan_status = DocumentScanStatus.PENDING
    db_session.flush()
    blocked = client.post(
        f"/api/v1/insurance/policies/{policy['id']}/extract",
        headers=patient["headers"],
        json={"document_id": document["id"]},
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "document_not_scanned"

    # A quarantine page is served for the owner, and never as clean.
    stored.scan_status = DocumentScanStatus.INFECTED
    stored.quarantined_at = stored.updated_at
    db_session.flush()
    quarantine = client.get(
        f"/api/v1/documents/{document['id']}", headers=patient["headers"]
    )
    assert quarantine.status_code == 200
    assert quarantine.json()["scan_status"] == "infected"
    assert (
        client.get(
            f"/api/v1/documents/{document['id']}/download", headers=patient["headers"]
        ).status_code
        == 422
    )


# --------------------------------------------------------------------------- AI extraction
def test_ai_ingestion_persists_coverage_for_review_with_provenance(client, patient):
    policy, document = _setup(client, patient)
    envelope = _envelope(
        document,
        patient,
        policy,
        coverage_facts=[
            {
                "field_key": "room_rent_limit",
                "value_numeric": "5000",
                "confidence": 0.9,
                "provenance": {"page": 3, "clause_reference": "4.2", "snippet_sha256": "abcdef12"},
            },
            {
                "field_key": "copay_percent",
                "value_percent": "10",
                "provenance": {"page": 4},
            },
            {
                "field_key": "exclusions",
                "value_text": "cosmetic surgery; self-inflicted injury",
                "provenance": {"page": 7, "section": "Exclusions"},
            },
        ],
        uncertainties=[
            {"field_key": "copay_percent", "reason": "Two figures printed", "confidence": 0.4}
        ],
        clause_interpretations=[
            {"clause_reference": "4.2", "summary": "Room rent is capped per day.", "page": 3}
        ],
    )
    response = _ingest(client, envelope)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] is True
    assert body["facts_written"] == 3
    assert body["verification_status"] == "needs_review"

    coverage = client.get(
        f"/api/v1/insurance/policies/{policy['id']}/coverage", headers=patient["headers"]
    ).json()
    assert coverage["field_count"] == 3
    statuses = {fact["field_key"]: fact["verification_status"] for fact in coverage["facts"]}
    assert set(statuses.values()) == {"needs_review"}
    assert coverage["has_extracted_document"] is True
    room = next(fact for fact in coverage["facts"] if fact["field_key"] == "room_rent_limit")
    assert room["provenance"]["page"] == 3
    assert room["provenance"]["clause_reference"] == "4.2"
    assert Decimal(room["original"]["value_numeric"]) == Decimal("5000")

    detail = client.get(
        f"/api/v1/insurance/policies/{policy['id']}", headers=patient["headers"]
    ).json()
    assert detail["policy"]["coverage_source"] == "document"
    assert detail["policy"]["coverage_confirmed"] is False
    assert "not been verified" in detail["policy"]["coverage_note"]

    receipts = client.get(
        f"/api/v1/insurance/policies/{policy['id']}/extractions", headers=patient["headers"]
    ).json()
    assert receipts[0]["extraction_id"] == envelope["extraction_id"]
    assert receipts[0]["uncertainties"][0]["reason"] == "Two figures printed"
    assert receipts[0]["clause_interpretations"][0]["clause_reference"] == "4.2"


def test_ai_cannot_assert_patient_confirmation(client, patient):
    policy, document = _setup(client, patient)
    for claimed in ("patient_confirmed", "insurer_verified", "verified"):
        envelope = _envelope(document, patient, policy, review_status=claimed)
        response = _ingest(client, envelope)
        assert response.status_code == 422, (claimed, response.text)


def test_insurance_contract_version_must_match(client, patient):
    policy, document = _setup(client, patient)
    response = _ingest(
        client, _envelope(document, patient, policy, contract_version="2025-01-old-contract")
    )
    assert response.status_code == 422
    assert "contract version" in response.json()["error"]["message"]


def test_extracted_fact_without_provenance_is_rejected(client, patient):
    policy, document = _setup(client, patient)
    missing = _envelope(
        document,
        patient,
        policy,
        coverage_facts=[{"field_key": "room_rent_limit", "value_numeric": "5000"}],
    )
    assert _ingest(client, missing).status_code == 422

    no_locator = _envelope(
        document,
        patient,
        policy,
        coverage_facts=[
            {
                "field_key": "room_rent_limit",
                "value_numeric": "5000",
                "provenance": {"snippet_sha256": "abcdef12"},
            }
        ],
    )
    assert _ingest(client, no_locator).status_code == 422


def test_invalid_coverage_values_are_rejected(client, patient):
    policy, _document = _setup(client, patient)
    base = f"/api/v1/insurance/policies/{policy['id']}/coverage"
    cases = [
        {"field_key": "copay_percent", "value_percent": "150"},
        {"field_key": "room_rent_limit", "value_numeric": "-1"},
        {"field_key": "waiting_period_months", "value_numeric": "9999"},
        {"field_key": "Room Rent", "value_numeric": "100"},
        {"field_key": "room_rent_limit", "value_text": "about five thousand"},
    ]
    for body in cases:
        response = client.post(base, headers=patient["headers"], json=body)
        assert response.status_code == 422, (body, response.text)


def test_patient_correction_keeps_the_extracted_original(client, patient, db_session):
    policy, document = _setup(client, patient)
    assert _ingest(client, _envelope(document, patient, policy)).status_code == 200

    corrected = client.patch(
        f"/api/v1/insurance/policies/{policy['id']}/coverage/room_rent_limit",
        headers=patient["headers"],
        json={"field_key": "room_rent_limit", "value_numeric": "4500", "note": "Policy says 4500"},
    )
    assert corrected.status_code == 200, corrected.text
    body = corrected.json()
    assert body["verification_status"] == "manually_entered"
    assert Decimal(body["value_numeric"]) == Decimal("4500")
    assert body["original"]["value_numeric"].startswith("5000")

    rows = list(
        db_session.scalars(
            select(InsuranceCoverageFact)
            .where(InsuranceCoverageFact.policy_id == uuid.UUID(policy["id"]))
            .where(InsuranceCoverageFact.field_key == "room_rent_limit")
        )
    )
    assert len(rows) == 2, "the extracted row must be superseded, not overwritten"
    superseded = [row for row in rows if not row.is_active][0]
    assert superseded.value_numeric == Decimal("5000")

    coverage = client.get(
        f"/api/v1/insurance/policies/{policy['id']}/coverage", headers=patient["headers"]
    ).json()
    assert coverage["field_count"] == 1
    assert coverage["unconfirmed_fields"] == []


def test_patient_confirmation_is_not_insurer_verification(client, patient):
    policy, document = _setup(client, patient)
    assert _ingest(client, _envelope(document, patient, policy)).status_code == 200

    confirmed = client.post(
        f"/api/v1/insurance/policies/{policy['id']}/confirm",
        headers=patient["headers"],
        json={},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["confirmed_fields"] == ["room_rent_limit"]
    fact = body["coverage"]["facts"][0]
    assert fact["verification_status"] == "patient_confirmed"
    assert body["coverage"]["coverage_confirmed"] is False
    assert body["coverage"]["coverage_source"] == "document"

    # Repeating a confirmation does not upgrade anything.
    again = client.post(
        f"/api/v1/insurance/policies/{policy['id']}/confirm",
        headers=patient["headers"],
        json={"field_keys": ["room_rent_limit"]},
    )
    assert again.status_code == 200
    assert again.json()["coverage"]["facts"][0]["verification_status"] == "patient_confirmed"


# --------------------------------------------------------------------------- insurer verification
def _manual_room_rent(client, patient, policy, value: str = "5000"):
    response = client.post(
        f"/api/v1/insurance/policies/{policy['id']}/coverage",
        headers=patient["headers"],
        json={"field_key": "room_rent_limit", "value_numeric": value},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_insurer_verification_requires_the_integration_and_records_attempt(
    client, patient, db_session
):
    policy = _policy(client, patient)
    _manual_room_rent(client, patient, policy)

    # A user cannot write the verified state directly...
    forged = client.patch(
        f"/api/v1/insurance/policies/{policy['id']}",
        headers=patient["headers"],
        json={"coverage_source": "insurer_verified"},
    )
    assert forged.status_code == 422

    # ...only the integration can, and only with a patient authorisation.
    missing_auth = client.post(
        f"/api/v1/insurance/policies/{policy['id']}/verify",
        headers=patient["headers"],
        json={"patient_authorization_reference": ""},
    )
    assert missing_auth.status_code == 422

    verified = client.post(
        f"/api/v1/insurance/policies/{policy['id']}/verify",
        headers=patient["headers"],
        json={"patient_authorization_reference": "STUB-VERIFIED:room_rent_limit=5000"},
    )
    assert verified.status_code == 200, verified.text
    body = verified.json()
    assert body["outcome"] == "verified"
    assert body["provider"] == "stub"  # mocked provider, not a real insurer
    assert body["coverage_confirmed"] is True
    assert body["verified_fields"] == ["room_rent_limit"]

    attempts = list(
        db_session.scalars(
            select(InsurerVerificationAttempt).where(
                InsurerVerificationAttempt.policy_id == uuid.UUID(policy["id"])
            )
        )
    )
    assert len(attempts) == 1
    assert attempts[0].patient_authorization_reference.startswith("STUB-VERIFIED")
    assert attempts[0].completed_at is not None


def test_insurer_verification_discrepancy_is_flagged(client, patient):
    policy = _policy(client, patient)
    _manual_room_rent(client, patient, policy, "5000")
    response = client.post(
        f"/api/v1/insurance/policies/{policy['id']}/verify",
        headers=patient["headers"],
        json={"patient_authorization_reference": "STUB-DISCREPANCY:room_rent_limit=6000"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["outcome"] == "discrepancy"
    assert body["coverage_confirmed"] is False
    assert body["discrepancies"][0]["field_key"] == "room_rent_limit"
    assert body["discrepancies"][0]["insurer"] == "6E+3"

    coverage = client.get(
        f"/api/v1/insurance/policies/{policy['id']}/coverage", headers=patient["headers"]
    ).json()
    assert coverage["facts"][0]["verification_status"] == "discrepancy"
    assert coverage["insurer_verified_fields"] == []


def test_insurer_verification_unsupported_and_unavailable_change_nothing(
    client, patient, db_session
):
    policy = _policy(client, patient)
    _manual_room_rent(client, patient, policy)

    unsupported = client.post(
        f"/api/v1/insurance/policies/{policy['id']}/verify",
        headers=patient["headers"],
        json={"patient_authorization_reference": "STUB-UNSUPPORTED"},
    )
    assert unsupported.status_code == 200
    assert unsupported.json()["outcome"] == "unsupported"
    assert unsupported.json()["coverage_confirmed"] is False

    unavailable = client.post(
        f"/api/v1/insurance/policies/{policy['id']}/verify",
        headers=patient["headers"],
        json={"patient_authorization_reference": "STUB-UNAVAILABLE"},
    )
    assert unavailable.status_code == 200
    assert unavailable.json()["outcome"] == "unavailable"

    coverage = client.get(
        f"/api/v1/insurance/policies/{policy['id']}/coverage", headers=patient["headers"]
    ).json()
    assert coverage["facts"][0]["verification_status"] == "manually_entered"
    attempts = list(
        db_session.scalars(
            select(InsurerVerificationAttempt).where(
                InsurerVerificationAttempt.policy_id == uuid.UUID(policy["id"])
            )
        )
    )
    assert len(attempts) == 2


# --------------------------------------------------------------------------- lifecycle & guidance
def test_policy_archive_hides_it_and_blocks_edits(client, patient):
    policy = _policy(client, patient)
    archived = client.post(
        f"/api/v1/insurance/policies/{policy['id']}/archive", headers=patient["headers"]
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived_at"] is not None

    listed = client.get(
        f"/api/v1/patients/{patient['profile_id']}/insurance/policies",
        headers=patient["headers"],
    ).json()
    assert listed == []
    visible = client.get(
        f"/api/v1/patients/{patient['profile_id']}/insurance/policies?include_archived=true",
        headers=patient["headers"],
    ).json()
    assert len(visible) == 1

    blocked = client.patch(
        f"/api/v1/insurance/policies/{policy['id']}",
        headers=patient["headers"],
        json={"sum_insured": "1"},
    )
    assert blocked.status_code == 409


def test_guidance_is_grounded_in_stored_coverage_and_audited(client, patient, db_session):
    from app.models.audit import AuditLog

    policy = _policy(client, patient)
    _manual_room_rent(client, patient, policy, "5000")
    client.post(
        f"/api/v1/insurance/policies/{policy['id']}/coverage",
        headers=patient["headers"],
        json={"field_key": "copay_percent", "value_percent": "10"},
    )

    response = client.get(
        f"/api/v1/insurance/policies/{policy['id']}/guidance?admission_type=emergency",
        headers=patient["headers"],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["admission_type"] == "emergency"
    assert "Guidance only" in body["disclaimer"]
    assert any("co-payment" in question for question in body["insurance_desk_questions"])
    assert any(item["field_key"] == "icu_limit" for item in body["data_gaps"])
    assert body["warnings"], "unverified coverage must be called out"
    assert body["required_documents"]
    assert body["claim_procedure"]

    actions = list(
        db_session.scalars(
            select(AuditLog.action).where(
                AuditLog.patient_id == uuid.UUID(patient["profile_id"])
            )
        )
    )
    assert "insurance.guidance_viewed" in actions


def test_expired_policy_is_flagged(client, patient):
    policy = _policy(
        client, patient, valid_from="2024-01-01", valid_to="2024-12-31"
    )
    detail = client.get(
        f"/api/v1/insurance/policies/{policy['id']}/coverage", headers=patient["headers"]
    ).json()
    assert detail["policy_expired"] is True

    guidance = client.get(
        f"/api/v1/insurance/policies/{policy['id']}/guidance", headers=patient["headers"]
    ).json()
    assert any("validity ended" in warning for warning in guidance["warnings"])


def test_extracted_dates_cannot_invert_the_validity_range(client, patient):
    policy, document = _setup(client, patient)
    response = _ingest(
        client,
        _envelope(
            document,
            patient,
            policy,
            policy_fields={"valid_from": "2027-01-01", "valid_to": "2026-01-01"},
        ),
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"


def test_endorsement_attachment_records_a_version(client, patient):
    policy = _policy(client, patient)
    upload = _upload(client, patient, name="endorsement.pdf")
    assert upload.status_code == 201
    response = _attach(
        client,
        patient,
        policy["id"],
        upload.json()["id"],
        role="endorsement",
        endorsement_reference="END-77",
    )
    assert response.status_code == 201, response.text
    versions = client.get(
        f"/api/v1/insurance/policies/{policy['id']}/versions", headers=patient["headers"]
    ).json()
    assert [version["kind"] for version in versions] == ["endorsement", "created"]
    assert versions[0]["endorsement_reference"] == "END-77"
