"""Audit recording.

Audit entries capture *who accessed what, when and with what outcome* — never
the clinical content itself. Context is passed through a redaction helper so
callers cannot accidentally persist PHI or secrets.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.logging import redact_mapping
from app.models.audit import AuditLog
from app.models.enums import ActorType, AuditOutcome
from app.db.base import utcnow


def _request_metadata(request: Request | None) -> tuple[str | None, str | None, str | None]:
    if request is None:
        return None, None, None
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    return (
        client_ip[:45] if client_ip else None,
        user_agent[:255] if user_agent else None,
        request_id[:64],
    )


def record_audit(
    db: Session,
    *,
    action: str,
    actor_type: ActorType = ActorType.USER,
    actor_user_id: uuid.UUID | None = None,
    actor_role: str | None = None,
    patient_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    request: Request | None = None,
    context: dict[str, Any] | None = None,
) -> AuditLog:
    """Append an audit entry to the current session (flushed, not committed)."""
    ip_address, user_agent, request_id = _request_metadata(request)
    entry = AuditLog(
        occurred_at=utcnow(),
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        patient_id=patient_id,
        action=action[:64],
        resource_type=(resource_type[:40] if resource_type else None),
        resource_id=(str(resource_id)[:64] if resource_id else None),
        outcome=outcome,
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
        context=redact_mapping(context or {}),
    )
    db.add(entry)
    db.flush()
    return entry
