"""Audit trail read endpoint.

The trail is append-only at the ORM level (see ``app/models/audit.py``); this
module only ever reads it, and reading it is itself recorded.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import NotFoundError
from app.core.pagination import paginate
from app.models.audit import AuditLog
from app.models.enums import AccessScope, UserRole
from app.schemas.audit import AuditEntryOut
from app.schemas.common import PageMeta, Paginated
from app.services.access import require_patient_access
from app.services.audit import record_audit

router = APIRouter(tags=["Audit"])


@router.get(
    "/patients/{patient_id}/audit",
    response_model=Paginated[AuditEntryOut],
    summary="Append-only access history for a patient record",
)
def read_audit_trail(
    patient_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    page: int = 1,
    page_size: int | None = None,
    action: str | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
) -> Paginated[AuditEntryOut]:
    ctx = require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.DEMOGRAPHICS,
        request=request,
        action="audit.view_denied",
    )
    if not ctx.can_write and UserRole(str(user.role)) != UserRole.ADMIN:
        raise NotFoundError("Audit history is not available for this record.")

    stmt = select(AuditLog).where(AuditLog.patient_id == patient_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if occurred_from is not None:
        stmt = stmt.where(AuditLog.occurred_at >= occurred_from)
    if occurred_to is not None:
        stmt = stmt.where(AuditLog.occurred_at <= occurred_to)
    stmt = stmt.order_by(AuditLog.occurred_at.desc())

    page_result = paginate(db, stmt, page=page, page_size=page_size)
    record_audit(
        db,
        action="audit.viewed",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=patient_id,
        resource_type="audit_log",
        resource_id=str(patient_id),
        request=request,
    )
    return Paginated[AuditEntryOut](
        items=[AuditEntryOut.model_validate(item) for item in page_result.items],
        meta=PageMeta(**page_result.meta()),
    )
