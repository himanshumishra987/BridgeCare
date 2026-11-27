"""Shared test fixtures.

The suite runs against in-memory SQLite by default; set
``BRIDGECARE_TEST_DATABASE_URL`` to an empty PostgreSQL database to run the same
tests against PostgreSQL instead. In that mode the schema is *not* built with
``create_all``: it must come from ``alembic upgrade head``, so the migration
itself is what the suite exercises.

Each test is wrapped in a transaction that is rolled back afterwards, so tests
never see each other's data. Document storage is redirected to a temporary
directory.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

# Configuration must be set before the app (and its cached settings) is imported.
_TMP_STORAGE = tempfile.mkdtemp(prefix="bridgecare-storage-")
os.environ["BRIDGECARE_ENVIRONMENT"] = "test"
os.environ["BRIDGECARE_SECRET_KEY"] = "unit-test-secret-key-0123456789abcdefghij"
os.environ["BRIDGECARE_STORAGE_ROOT"] = _TMP_STORAGE
os.environ["BRIDGECARE_AI_SERVICE_KEY"] = "unit-test-ai-service-key"
os.environ["BRIDGECARE_HOSPITAL_DIRECTORY_PROVIDER"] = "none"
# Deterministic stand-in scanner: every upload is scanned at upload time and the
# EICAR-TEST marker yields an infected verdict. Never clean-by-default.
os.environ["BRIDGECARE_DOCUMENT_SCANNER"] = "stub"
os.environ["BRIDGECARE_INSURER_VERIFICATION_PROVIDER"] = "stub"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import NullPool, StaticPool  # noqa: E402

import app.models  # noqa: F401,E402  (registers every table)
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import create_app  # noqa: E402

TEST_DATABASE_URL = os.environ.get("BRIDGECARE_TEST_DATABASE_URL", "").strip()

DEFAULT_PASSWORD = "CorrectHorseBattery9"
SCAN_MARKER_INFECTED = b"EICAR-TEST"
MINIMAL_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< >>\n%%EOF\n"
AI_SERVICE_KEY = "unit-test-ai-service-key"


@pytest.fixture(scope="session")
def engine():
    if TEST_DATABASE_URL:
        engine = create_engine(TEST_DATABASE_URL, poolclass=NullPool, future=True)
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        if not revision:
            raise RuntimeError(
                "BRIDGECARE_TEST_DATABASE_URL is set but the database has no migrated "
                "schema; run `alembic upgrade head` first."
            )
        yield engine
        engine.dispose()
        return

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(engine) -> Iterator[Session]:
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture()
def app(db_session: Session):
    application = create_app()

    def override_get_db() -> Iterator[Session]:
        yield db_session

    application.dependency_overrides[get_db] = override_get_db
    return application


@pytest.fixture()
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def ai_headers(key: str = AI_SERVICE_KEY) -> dict[str, str]:
    return {"X-AI-Service-Key": key}


def register(
    client: TestClient,
    email: str,
    full_name: str = "Test Patient",
    password: str = DEFAULT_PASSWORD,
) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def profile_id_for(client: TestClient, token: str) -> str:
    response = client.get("/api/v1/auth/me", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    return response.json()["patient_profile_id"]


def user_id_for(client: TestClient, token: str) -> str:
    response = client.get("/api/v1/auth/me", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    return response.json()["user"]["id"]


def make_account(client: TestClient, email: str, full_name: str = "Test Patient") -> dict:
    tokens = register(client, email, full_name=full_name)
    return {
        "email": email,
        "token": tokens["access_token"],
        "refresh": tokens["refresh_token"],
        "headers": auth_headers(tokens["access_token"]),
        "profile_id": profile_id_for(client, tokens["access_token"]),
        "user_id": user_id_for(client, tokens["access_token"]),
    }


@pytest.fixture()
def patient(client: TestClient) -> dict:
    return make_account(client, "asha.patient@example.com", "Asha Rao")


@pytest.fixture()
def other_patient(client: TestClient) -> dict:
    return make_account(client, "ravi.patient@example.com", "Ravi Menon")


@pytest.fixture()
def caregiver(client: TestClient, patient: dict) -> dict:
    """A caregiver who has accepted a full read grant from ``patient``."""
    account = make_account(client, "nurse.caregiver@example.com", "Nurse Joy")
    granted = client.post(
        f"/api/v1/patients/{patient['profile_id']}/consents",
        headers=patient["headers"],
        json={
            "grantee_email": account["email"],
            "scopes": [
                "demographics",
                "documents",
                "records",
                "biomarkers",
                "medications",
                "wellness",
                "emergency",
                "insurance",
                "family",
                "analytics",
            ],
            "purpose": "care_coordination",
        },
    )
    assert granted.status_code == 201, granted.text
    consent_id = granted.json()["id"]
    accepted = client.post(
        f"/api/v1/consents/{consent_id}/accept", headers=account["headers"]
    )
    assert accepted.status_code == 200, accepted.text
    account["consent_id"] = consent_id
    return account
