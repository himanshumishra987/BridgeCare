"""Consent-aware share link tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.models.consent import ShareLink


def _seed(client, patient):
    client.post(
        f"/api/v1/patients/{patient['profile_id']}/records",
        headers=patient["headers"],
        json={
            "category": "lab_report",
            "title": "Shared lab report",
            "recorded_at": "2025-01-01T00:00:00Z",
            "summary": "Shared with a specialist",
        },
    )
    client.post(
        f"/api/v1/patients/{patient['profile_id']}/medications",
        headers=patient["headers"],
        json={"generic_name": "metformin", "started_on": "2025-01-01"},
    )


def _create_link(client, patient, scopes=None, **overrides):
    payload = {"scopes": scopes or ["records"], "expires_in_days": 3}
    payload.update(overrides)
    return client.post(
        f"/api/v1/patients/{patient['profile_id']}/share-links",
        headers=patient["headers"],
        json=payload,
    )


def test_share_link_exposes_only_granted_scopes(client, patient):
    _seed(client, patient)
    created = _create_link(client, patient, scopes=["records"], label="Cardiology")
    assert created.status_code == 201, created.text
    body = created.json()
    token = body["token"]
    assert body["share_path"].endswith(token)

    shared = client.get(f"/api/v1/share/{token}")
    assert shared.status_code == 200
    view = shared.json()
    assert view["share"]["label"] == "Cardiology"
    assert len(view["records"]) == 1
    assert view["records"][0]["title"] == "Shared lab report"
    assert "patient" not in view or view["patient"] is None
    assert view["medications"] is None


def test_share_link_never_returns_its_token_again(client, patient):
    created = _create_link(client, patient).json()
    listing = client.get(
        f"/api/v1/patients/{patient['profile_id']}/share-links",
        headers=patient["headers"],
    )
    assert listing.status_code == 200
    assert created["token"] not in listing.text
    assert listing.json()[0]["token_prefix"]


def test_public_share_cannot_request_blocked_scopes(client, patient):
    response = _create_link(client, patient, scopes=["insurance"])
    assert response.status_code == 422

    emergency = _create_link(client, patient, scopes=["emergency"])
    assert emergency.status_code == 422

    family = _create_link(client, patient, scopes=["family"])
    assert family.status_code == 422


def test_expired_share_link_is_rejected(client, db_session, patient):
    token = _create_link(client, patient).json()["token"]
    link = db_session.query(ShareLink).filter(ShareLink.token_hash.is_not(None)).one()
    link.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.flush()

    response = client.get(f"/api/v1/share/{token}")
    assert response.status_code == 404


def test_revoked_share_link_is_rejected(client, patient):
    created = _create_link(client, patient).json()
    revoked = client.post(
        f"/api/v1/share-links/{created['link']['id']}/revoke", headers=patient["headers"]
    )
    assert revoked.status_code == 200
    assert client.get(f"/api/v1/share/{created['token']}").status_code == 404


def test_usage_limit_is_enforced(client, patient):
    created = _create_link(client, patient, max_uses=1).json()
    token = created["token"]
    assert client.get(f"/api/v1/share/{token}").status_code == 200
    assert client.get(f"/api/v1/share/{token}").status_code == 404


def test_share_link_expiry_cannot_exceed_policy(client, patient):
    response = _create_link(client, patient, expires_in_days=3650)
    assert response.status_code == 422


def test_unknown_token_is_not_found(client):
    response = client.get(f"/api/v1/share/{uuid.uuid4().hex}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_share_access_is_audited(client, patient):
    token = _create_link(client, patient, scopes=["records"]).json()["token"]
    client.get(f"/api/v1/share/{token}")

    audit = client.get(
        f"/api/v1/patients/{patient['profile_id']}/audit", headers=patient["headers"]
    )
    assert audit.status_code == 200
    entries = audit.json()["items"]
    share_entries = [entry for entry in entries if entry["action"] == "share_link.accessed"]
    assert share_entries
    assert share_entries[0]["actor_type"] == "share_link"
    assert share_entries[0]["actor_user_id"] is None


def test_only_consent_manager_can_create_links(client, patient, caregiver):
    response = client.post(
        f"/api/v1/patients/{patient['profile_id']}/share-links",
        headers=caregiver["headers"],
        json={"scopes": ["records"], "expires_in_days": 1},
    )
    assert response.status_code == 404
