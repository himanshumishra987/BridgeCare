"""Consent-aware sharing endpoints.

``POST /patients/{id}/share-links`` creates an expiring, usage-limited link and
returns the plaintext token exactly once. ``GET /share/{token}`` is the only
unauthenticated endpoint and returns a whitelisted projection; every resolution
is audited.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import ConflictError, NotFoundError
from app.models.consent import ShareLink
from app.models.enums import AccessScope
from app.schemas.sharing import SharedViewOut, ShareLinkCreate, ShareLinkCreatedOut, ShareLinkOut
from app.services.access import get_patient_or_404, require_consent_manager
from app.services.audit import record_audit
from app.services.sharing import build_shared_view, create_share_link, resolve_share_link

router = APIRouter(tags=["Sharing"])

LINK_NOT_FOUND = "Share link not found."


def _now() -> datetime:
    return datetime.now(UTC)


@router.post(
    "/patients/{patient_id}/share-links",
    response_model=ShareLinkCreatedOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create an expiring share link (token shown once)",
)
def create_link(
    patient_id: uuid.UUID,
    payload: ShareLinkCreate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> ShareLinkCreatedOut:
    patient = get_patient_or_404(db, patient_id)
    require_consent_manager(db, user=user, patient=patient, request=request)
    link, token = create_share_link(
        db,
        patient=patient,
        created_by_user_id=user.id,
        scopes=[scope.value for scope in payload.scopes],
        expires_at=_now() + timedelta(days=payload.expires_in_days),
        max_uses=payload.max_uses,
        label=payload.label,
        request=request,
    )
    return ShareLinkCreatedOut(
        link=ShareLinkOut.model_validate(link),
        token=token,
        share_path=f"/api/v1/share/{token}",
    )


@router.get(
    "/patients/{patient_id}/share-links",
    response_model=list[ShareLinkOut],
    summary="List share links (tokens are never returned again)",
)
def list_links(
    patient_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> list[ShareLinkOut]:
    patient = get_patient_or_404(db, patient_id)
    require_consent_manager(db, user=user, patient=patient, request=request)
    rows = db.scalars(
        select(ShareLink)
        .where(ShareLink.patient_id == patient.id)
        .order_by(ShareLink.created_at.desc())
    )
    return [ShareLinkOut.model_validate(row) for row in rows]


@router.post(
    "/share-links/{link_id}/revoke",
    response_model=ShareLinkOut,
    summary="Revoke a share link immediately",
)
def revoke_link(
    link_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> ShareLink:
    link = db.get(ShareLink, link_id)
    if link is None:
        raise NotFoundError(LINK_NOT_FOUND)
    patient = get_patient_or_404(db, link.patient_id)
    require_consent_manager(db, user=user, patient=patient, request=request)
    if link.revoked_at is None:
        link.revoked_at = _now()
        db.flush()
        record_audit(
            db,
            action="share_link.revoked",
            actor_user_id=user.id,
            actor_role=str(user.role),
            patient_id=link.patient_id,
            resource_type="share_link",
            resource_id=str(link.id),
            request=request,
        )
    return link


@router.get(
    "/share/{token}",
    response_model=SharedViewOut,
    summary="Read a shared record subset with a share token (no login required)",
)
def read_shared_record(token: str, request: Request, db: DbSession) -> SharedViewOut:
    link = resolve_share_link(db, token=token, request=request)
    payload = build_shared_view(db, link=link)
    return SharedViewOut.model_validate(payload)
