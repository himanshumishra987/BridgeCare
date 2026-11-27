"""Unified personal health record tests: provenance, search, revisions, verification."""

from __future__ import annotations

from tests.conftest import MINIMAL_PDF


def _create_record(client, patient, **overrides):
    payload = {
        "category": "lab_report",
        "title": "HbA1c report",
        "recorded_at": "2025-03-04T08:30:00Z",
        "summary": "Quarterly diabetes review",
        "provider_name": "Dr. Iyer",
        "facility_name": "Sunrise Diagnostics",
    }
    payload.update(overrides)
    response = client.post(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=patient["headers"],
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_record_starts_unverified_with_revision(client, patient):
    record = _create_record(client, patient)
    assert record["status"] == "unverified"
    assert record["origin"] == "user"

    revisions = client.get(
        f"/api/v1/records/{record['id']}/revisions", headers=patient["headers"]
    )
    assert revisions.status_code == 200
    history = revisions.json()
    assert len(history) == 1
    assert history[0]["change_type"] == "create"


def test_record_keeps_document_provenance(client, patient):
    upload = client.post(
        f"/api/v1/patients/{patient['profile_id']}/documents",
        headers=patient["headers"],
        files={"file": ("hba1c.pdf", MINIMAL_PDF, "application/pdf")},
    )
    document_id = upload.json()["id"]
    record = _create_record(
        client,
        patient,
        source_document_id=document_id,
        provenance={"page": 1, "confidence": 0.91, "model_version": "gemini-x"},
    )
    assert record["source_document_id"] == document_id
    assert record["provenance"]["page"] == 1
    assert record["provenance"]["confidence"] == 0.91


def test_source_document_must_belong_to_patient(client, patient, other_patient):
    upload = client.post(
        f"/api/v1/patients/{other_patient['profile_id']}/documents",
        headers=other_patient["headers"],
        files={"file": ("other.pdf", MINIMAL_PDF, "application/pdf")},
    )
    foreign_document = upload.json()["id"]
    response = client.post(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=patient["headers"],
        json={
            "category": "lab_report",
            "title": "Tampered",
            "recorded_at": "2025-03-04T08:30:00Z",
            "source_document_id": foreign_document,
        },
    )
    assert response.status_code == 422


def test_search_filter_and_ordering(client, patient):
    _create_record(client, patient, title="Older panel", recorded_at="2024-01-01T00:00:00Z")
    _create_record(
        client,
        patient,
        title="Newer panel",
        category="imaging",
        recorded_at="2025-06-01T00:00:00Z",
    )
    _create_record(
        client, patient, title="Thyroid panel", recorded_at="2025-02-01T00:00:00Z"
    )

    listing = client.get(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=patient["headers"],
        params={"page": 1, "page_size": 2},
    )
    assert listing.status_code == 200
    body = listing.json()
    assert body["meta"]["total"] == 3
    assert body["meta"]["pages"] == 2
    assert [item["title"] for item in body["items"]] == ["Newer panel", "Thyroid panel"]

    filtered = client.get(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=patient["headers"],
        params={"category": "imaging"},
    )
    assert [item["title"] for item in filtered.json()["items"]] == ["Newer panel"]

    searched = client.get(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=patient["headers"],
        params={"q": "thyroid"},
    )
    assert len(searched.json()["items"]) == 1

    windowed = client.get(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=patient["headers"],
        params={"recorded_from": "2025-01-15T00:00:00Z"},
    )
    assert len(windowed.json()["items"]) == 2


def test_timeline_merges_records_and_measurements(client, patient):
    _create_record(client, patient, recorded_at="2025-01-01T00:00:00Z", title="Visit")
    client.post(
        f"/api/v1/patients/{patient['profile_id']}/biomarkers",
        headers=patient["headers"],
        json={
            "analyte_key": "hba1c",
            "analyte_display": "HbA1c",
            "value_numeric": "6.4",
            "unit": "%",
            "collected_at": "2025-05-01T00:00:00Z",
        },
    )
    timeline = client.get(
        f"/api/v1/patients/{patient['profile_id']}/records/timeline",
        headers=patient["headers"],
    )
    assert timeline.status_code == 200
    entries = timeline.json()
    assert entries[0]["entry_type"] == "measurement"
    assert any(entry["entry_type"] == "record" for entry in entries)


def test_editing_creates_append_only_revision(client, patient):
    record = _create_record(client, patient)
    edited = client.patch(
        f"/api/v1/records/{record['id']}",
        headers=patient["headers"],
        json={"title": "HbA1c report (corrected)", "change_reason": "Typo in title"},
    )
    assert edited.status_code == 200
    assert edited.json()["title"] == "HbA1c report (corrected)"

    history = client.get(
        f"/api/v1/records/{record['id']}/revisions", headers=patient["headers"]
    ).json()
    assert [item["revision_number"] for item in history] == [1, 2]
    assert history[1]["change_type"] == "edit"
    assert history[1]["before"]["title"] == "HbA1c report"
    assert history[1]["after"]["title"] == "HbA1c report (corrected)"
    assert history[1]["change_reason"] == "Typo in title"


def test_read_only_fields_cannot_be_edited(client, patient):
    record = _create_record(client, patient)
    response = client.patch(
        f"/api/v1/records/{record['id']}",
        headers=patient["headers"],
        json={"status": "verified"},
    )
    assert response.status_code == 422


def test_verification_state_machine(client, patient):
    record = _create_record(client, patient)
    url = f"/api/v1/records/{record['id']}/verify"

    skipped = client.post(url, headers=patient["headers"], json={"status": "verified"})
    assert skipped.status_code == 422

    pending = client.post(
        url, headers=patient["headers"], json={"status": "pending_review"}
    )
    assert pending.status_code == 200
    assert pending.json()["status"] == "pending_review"

    verified = client.post(
        url, headers=patient["headers"], json={"status": "verified", "note": "Checked"}
    )
    assert verified.status_code == 200
    assert verified.json()["status"] == "verified"
    assert verified.json()["verified_at"] is not None

    reopened = client.post(
        url, headers=patient["headers"], json={"status": "pending_review"}
    )
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "pending_review"


def test_verification_is_recorded_in_history(client, patient):
    record = _create_record(client, patient)
    client.post(
        f"/api/v1/records/{record['id']}/verify",
        headers=patient["headers"],
        json={"status": "pending_review"},
    )
    history = client.get(
        f"/api/v1/records/{record['id']}/revisions", headers=patient["headers"]
    ).json()
    assert history[-1]["change_type"] == "verification"
    assert history[-1]["after"]["status"] == "pending_review"
