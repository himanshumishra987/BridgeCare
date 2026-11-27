"""Append-only audit log.

Audit rows contain metadata only: never medical content, OCR text, document
bodies or secrets. Both ORM-level and API-level paths forbid mutation so the
access trail for a patient cannot be rewritten by anyone, including an
administrator.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, event
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSONColumn, Base, UUIDPrimaryKeyMixin, utcnow
from app.models.enums import ActorType, AuditOutcome, enum_type


class AuditLogImmutableError(RuntimeError):
    """Raised when code attempts to update or delete an audit entry."""


class AuditLog(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "audit_logs"

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, index=True
    )
    actor_type: Mapped[ActorType] = mapped_column(
        enum_type(ActorType, 20), nullable=False, default=ActorType.USER
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    actor_role: Mapped[str | None] = mapped_column(String(20))
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(40), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(64))
    outcome: Mapped[AuditOutcome] = mapped_column(
        enum_type(AuditOutcome, 20), nullable=False, default=AuditOutcome.SUCCESS
    )
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    request_id: Mapped[str | None] = mapped_column(String(64))
    context: Mapped[dict[str, Any]] = mapped_column(JSONColumn, nullable=False, default=dict)


@event.listens_for(AuditLog, "before_update")
def _forbid_audit_update(_mapper: Any, _connection: Any, _target: AuditLog) -> None:
    raise AuditLogImmutableError("Audit log entries are append-only and cannot be modified.")


@event.listens_for(AuditLog, "before_delete")
def _forbid_audit_delete(_mapper: Any, _connection: Any, _target: AuditLog) -> None:
    raise AuditLogImmutableError("Audit log entries are append-only and cannot be deleted.")
