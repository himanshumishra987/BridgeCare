"""Language-preference persistence tests.

The preference must survive a session reload: signing out and back in, or
re-reading the profile, must return the saved value rather than the default.
"""

from __future__ import annotations

from tests.conftest import DEFAULT_PASSWORD, auth_headers, make_account, register


def test_registration_defaults_language_to_english(client) -> None:
    tokens = register(client, "lang.default@example.com")
    profile = client.get(
        "/api/v1/patients/me", headers=auth_headers(tokens["access_token"])
    )
    assert profile.status_code == 200, profile.text
    assert profile.json()["primary_language"] == "en"

    me = client.get("/api/v1/auth/me", headers=auth_headers(tokens["access_token"]))
    assert me.json()["primary_language"] == "en"


def test_language_is_persisted_and_returned_by_auth_me(client) -> None:
    account = make_account(client, "lang.update@example.com")
    updated = client.patch(
        "/api/v1/patients/me",
        headers=account["headers"],
        json={"primary_language": "hi"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["primary_language"] == "hi"

    me = client.get("/api/v1/auth/me", headers=account["headers"])
    assert me.json()["primary_language"] == "hi"


def test_language_survives_sign_out_and_sign_in(client) -> None:
    account = make_account(client, "lang.reload@example.com")
    client.patch(
        "/api/v1/patients/me",
        headers=account["headers"],
        json={"primary_language": "ta"},
    )
    logged_out = client.post(
        "/api/v1/auth/logout", json={"refresh_token": account["refresh"]}
    )
    assert logged_out.status_code == 200, logged_out.text

    login = client.post(
        "/api/v1/auth/login",
        json={"email": account["email"], "password": DEFAULT_PASSWORD},
    )
    assert login.status_code == 200, login.text
    fresh = auth_headers(login.json()["access_token"])

    me = client.get("/api/v1/auth/me", headers=fresh)
    assert me.json()["primary_language"] == "ta"
    profile = client.get("/api/v1/patients/me", headers=fresh)
    assert profile.json()["primary_language"] == "ta"


def test_granted_caregiver_reads_saved_language(client, patient, caregiver) -> None:
    client.patch(
        "/api/v1/patients/me", headers=patient["headers"], json={"primary_language": "bn"}
    )
    response = client.get(
        f"/api/v1/patients/{patient['profile_id']}", headers=caregiver["headers"]
    )
    assert response.status_code == 200, response.text
    assert response.json()["primary_language"] == "bn"


def test_language_rejects_values_outside_the_allowed_length(client) -> None:
    account = make_account(client, "lang.invalid@example.com")
    for value in ("e", "x" * 17):
        response = client.patch(
            "/api/v1/patients/me",
            headers=account["headers"],
            json={"primary_language": value},
        )
        assert response.status_code == 422, response.text
