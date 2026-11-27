"""Authentication, session and account-security tests."""

from __future__ import annotations

from tests.conftest import DEFAULT_PASSWORD, auth_headers, register


def test_register_creates_patient_account_with_profile(client):
    tokens = register(client, "new.user@example.com", "New User")
    assert tokens["token_type"] == "bearer"
    assert tokens["access_token"] and tokens["refresh_token"]

    me = client.get("/api/v1/auth/me", headers=auth_headers(tokens["access_token"]))
    assert me.status_code == 200
    body = me.json()
    assert body["user"]["role"] == "patient"
    assert body["user"]["email"] == "new.user@example.com"
    assert body["patient_profile_id"] is not None


def test_register_normalises_email_case(client):
    tokens = register(client, "MiXeD.Case@Example.com")
    me = client.get("/api/v1/auth/me", headers=auth_headers(tokens["access_token"]))
    assert me.json()["user"]["email"] == "mixed.case@example.com"


def test_register_rejects_duplicate_email(client):
    register(client, "dup@example.com")
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "dup@example.com", "password": DEFAULT_PASSWORD, "full_name": "Dup"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_register_cannot_self_assign_privileged_role(client):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": "sneaky@example.com",
            "password": DEFAULT_PASSWORD,
            "full_name": "Sneaky",
            "role": "admin",
        },
    )
    assert response.status_code == 422


def test_register_rejects_weak_password(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "weak@example.com", "password": "1111111111", "full_name": "Weak"},
    )
    assert response.status_code == 422


def test_login_rejects_wrong_password_with_generic_error(client):
    register(client, "login@example.com")
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "WrongPassword123"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid email or password."


def test_login_unknown_account_returns_identical_error(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@example.com", "password": DEFAULT_PASSWORD},
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid email or password."


def test_login_succeeds_with_correct_credentials(client):
    register(client, "good@example.com")
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "GOOD@example.com", "password": DEFAULT_PASSWORD},
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_protected_endpoint_requires_bearer_token(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


def test_malformed_token_is_rejected(client):
    response = client.get("/api/v1/auth/me", headers=auth_headers("not-a-jwt"))
    assert response.status_code == 401


def test_refresh_rotates_token_and_rejects_reuse(client):
    tokens = register(client, "rotate@example.com")
    first = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert first.status_code == 200
    assert first.json()["refresh_token"] != tokens["refresh_token"]

    replay = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert replay.status_code == 401


def test_refresh_token_cannot_be_used_as_access_token(client):
    tokens = register(client, "typing@example.com")
    response = client.get(
        "/api/v1/auth/me", headers=auth_headers(tokens["refresh_token"])
    )
    assert response.status_code == 401


def test_logout_revokes_refresh_token(client):
    tokens = register(client, "logout@example.com")
    assert (
        client.post(
            "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}
        ).status_code
        == 200
    )
    response = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 401


def test_password_change_revokes_sessions_and_old_password(client):
    tokens = register(client, "pwchange@example.com")
    new_password = "BrandNewPassword42"
    changed = client.post(
        "/api/v1/auth/password",
        headers=auth_headers(tokens["access_token"]),
        json={"current_password": DEFAULT_PASSWORD, "new_password": new_password},
    )
    assert changed.status_code == 200

    stale_refresh = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert stale_refresh.status_code == 401

    old_login = client.post(
        "/api/v1/auth/login",
        json={"email": "pwchange@example.com", "password": DEFAULT_PASSWORD},
    )
    assert old_login.status_code == 401

    new_login = client.post(
        "/api/v1/auth/login",
        json={"email": "pwchange@example.com", "password": new_password},
    )
    assert new_login.status_code == 200


def test_password_change_requires_current_password(client):
    tokens = register(client, "pwguard@example.com")
    response = client.post(
        "/api/v1/auth/password",
        headers=auth_headers(tokens["access_token"]),
        json={"current_password": "WrongCurrent123", "new_password": "AnotherPassword42"},
    )
    assert response.status_code == 401


def test_repeated_failures_lock_the_account(client):
    register(client, "lockme@example.com")
    for _ in range(8):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "lockme@example.com", "password": "WrongPassword123"},
        )
        assert response.status_code == 401
    blocked = client.post(
        "/api/v1/auth/login",
        json={"email": "lockme@example.com", "password": DEFAULT_PASSWORD},
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
