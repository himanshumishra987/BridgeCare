"""Secure document storage tests."""

from __future__ import annotations

from tests.conftest import MINIMAL_PDF

PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _upload(client, patient, filename="report.pdf", content=MINIMAL_PDF, content_type="application/pdf", **data):
    return client.post(
        f"/api/v1/patients/{patient['profile_id']}/documents",
        headers=patient["headers"],
        files={"file": (filename, content, content_type)},
        data=data,
    )


def test_upload_pdf_stores_metadata_and_allows_download(client, patient):
    response = _upload(client, patient, kind="lab_report")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["content_type"] == "application/pdf"
    assert body["kind"] == "lab_report"
    assert body["byte_size"] == len(MINIMAL_PDF)
    assert len(body["sha256"]) == 64
    assert "storage_key" not in body

    download = client.get(
        f"/api/v1/documents/{body['id']}/download", headers=patient["headers"]
    )
    assert download.status_code == 200
    assert download.content == MINIMAL_PDF
    assert download.headers["cache-control"] == "no-store"
    assert download.headers["x-content-type-options"] == "nosniff"


def test_download_response_never_exposes_other_patients_document(client, patient, other_patient):
    document = _upload(client, patient).json()
    response = client.get(
        f"/api/v1/documents/{document['id']}/download", headers=other_patient["headers"]
    )
    assert response.status_code == 404


def test_non_document_payload_is_rejected(client, patient):
    response = _upload(
        client, patient, filename="notes.pdf", content=b"just some text", content_type="application/pdf"
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_declared_type_must_match_contents(client, patient):
    response = _upload(client, patient, content=MINIMAL_PDF, content_type="image/png")
    assert response.status_code == 415


def test_png_is_accepted(client, patient):
    response = _upload(client, patient, filename="scan.png", content=PNG_HEADER, content_type="image/png")
    assert response.status_code == 201
    assert response.json()["content_type"] == "image/png"


def test_filename_is_sanitised(client, patient):
    response = _upload(client, patient, filename="../../../etc/passwd.pdf")
    assert response.status_code == 201
    stored = response.json()["original_filename"]
    assert "/" not in stored and "\\" not in stored
    assert stored.endswith(".pdf")


def test_duplicate_upload_is_deduplicated(client, patient):
    first = _upload(client, patient)
    assert first.status_code == 201
    second = _upload(client, patient)
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


def test_archive_hides_and_blocks_document(client, patient):
    document = _upload(client, patient).json()
    archived = client.post(
        f"/api/v1/documents/{document['id']}/archive", headers=patient["headers"]
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    listing = client.get(
        f"/api/v1/patients/{patient['profile_id']}/documents", headers=patient["headers"]
    )
    assert listing.json()["meta"]["total"] == 0

    download = client.get(
        f"/api/v1/documents/{document['id']}/download", headers=patient["headers"]
    )
    assert download.status_code == 409


def test_document_listing_is_paginated_and_filterable(client, patient):
    _upload(client, patient, kind="lab_report")
    _upload(client, patient, filename="scan.png", content=PNG_HEADER, content_type="image/png", kind="insurance")

    listing = client.get(
        f"/api/v1/patients/{patient['profile_id']}/documents",
        headers=patient["headers"],
        params={"page": 1, "page_size": 1},
    )
    assert listing.status_code == 200
    assert listing.json()["meta"]["total"] == 2
    assert len(listing.json()["items"]) == 1

    filtered = client.get(
        f"/api/v1/patients/{patient['profile_id']}/documents",
        headers=patient["headers"],
        params={"kind": "insurance"},
    )
    assert filtered.json()["meta"]["total"] == 1


def test_extractions_are_empty_until_the_ai_engine_submits(client, patient):
    document = _upload(client, patient).json()
    response = client.get(
        f"/api/v1/documents/{document['id']}/extractions", headers=patient["headers"]
    )
    assert response.status_code == 200
    assert response.json() == []


def test_upload_requires_write_access(client, patient, caregiver):
    response = client.post(
        f"/api/v1/patients/{patient['profile_id']}/documents",
        headers=caregiver["headers"],
        files={"file": ("caregiver.pdf", MINIMAL_PDF, "application/pdf")},
    )
    assert response.status_code == 404
