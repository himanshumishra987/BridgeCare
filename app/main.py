"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)

API_DESCRIPTION = """
BridgeCare backend for AI-assisted personal health record organisation.

**Security model**

* Bearer JWT access tokens (short lived) plus rotating, revocable refresh tokens.
* Every patient-scoped route resolves access through one authorization layer:
  the record owner, or an active, unexpired, explicitly accepted consent grant
  containing the required scope. Being a family member grants nothing by itself.
* Administrators have no implicit access to health data.
* Unauthorized and non-existent patients both return `404` to prevent IDOR.
* Sensitive reads and all share-link accesses are written to an append-only audit log.

**Clinical posture**

* Only a human may mark a record as verified. The AI engine submits
  `pending_review` records and cannot assert verification.
* Interaction and herb–drug warnings come only from curated, cited rules and are
  returned with their professional-review status. No dosage advice is generated.
* Insurance coverage and claim status are shown as user-reported until an
  insurer-side verification reference exists.
"""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.resolved_storage_root.mkdir(parents=True, exist_ok=True)
    logger.info(
        "BridgeCare API starting (environment=%s, ai_contract_enabled=%s)",
        settings.environment,
        settings.ai_contract_enabled,
    )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        description=API_DESCRIPTION,
        version="1.0.0",
        lifespan=lifespan,
        openapi_tags=[
            {"name": "Authentication", "description": "Accounts, sessions and tokens."},
            {"name": "Patient profiles", "description": "Demographics and profile data."},
            {"name": "Documents", "description": "Secure upload and retrieval."},
            {"name": "Health records", "description": "Unified record and verification history."},
            {"name": "Biomarkers & analytics", "description": "Longitudinal measurements."},
            {"name": "Medications", "description": "History, schedules, reminders and safety checks."},
            {"name": "Wellness (AYUSH)", "description": "Non-allopathic care records."},
            {"name": "Family & consent", "description": "Dependants and granular consent grants."},
            {"name": "Sharing", "description": "Expiring, revocable share links."},
            {"name": "Emergency support", "description": "Contacts, emergency summary, hospital lookup."},
            {"name": "Insurance", "description": "Policies, schemes, hospitalisations and claims."},
            {"name": "Audit", "description": "Append-only access history."},
            {"name": "AI engine (internal)", "description": "Service-key protected ingestion contract."},
        ],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    if settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.allowed_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
        )

    @app.middleware("http")
    async def security_headers(request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith(settings.api_v1_prefix):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.get("/healthz", tags=["Operations"], summary="Liveness probe")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "environment": settings.environment}

    return app


app = create_app()
