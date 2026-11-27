"""Human verification of medical records.

The AI engine can only create records in ``PENDING_REVIEW``. This module owns
the legal transitions and writes an immutable revision row for every change, so
"who verified what, when, and from which prior state" is always answerable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, ValidationAppError
from app.models.enums import VerificationStatus
from app.models.record import HealthRecord, RecordRevision
from app.models.user import User

ALLOWED_TRANSITIONS: dict[VerificationStatus, frozenset[VerificationStatus]] = {
    VerificationStatus.UNVERIFIED: frozenset({VerificationStatus.PENDING_REVIEW}),
    VerificationStatus.PENDING_REVIEW: frozenset(
        {VerificationStatus.VERIFIED, VerificationStatus.REJECTED}
    ),
    VerificationStatus.VERIFIED: frozenset({VerificationStatus.PENDING_REVIEW}),
    VerificationStatus.REJECTED: frozenset({VerificationStatus.PENDING_REVIEW}),
}


def can_transition(current: VerificationStatus, target: VerificationStatus) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def snapshot(record: HealthRecord) -> dict[str, Any]:
    """Serializable snapshot used for revision history (metadata only)."""
    return {
        "category": str(record.category),
        "title": record.title,
        "summary": record.summary,
        "recorded_at": record.recorded_at.isoformat() if record.recorded_at else None,
        "provider_name": record.provider_name,
        "facility_name": record.facility_name,
        "status": str(record.status),
        "verified_at": record.verified_at.isoformat() if record.verified_at else None,
        "provenance": record.provenance or {},
    }


def next_revision_number(db: Session, record_id: uuid.UUID) -> int:
    current_max = db.scalar(
        select(func.max(RecordRevision.revision_number)).where(
            RecordRevision.record_id == record_id
        )
    )
    return int(current_max or 0) + 1


def add_revision(
    db: Session,
    *,
    record: HealthRecord,
    before: dict[str, Any],
    after: dict[str, Any],
    actor_user_id: uuid.UUID | None,
    change_type: str,
    change_reason: str | None = None,
) -> RecordRevision:
    revision = RecordRevision(
        record_id=record.id,
        revision_number=next_revision_number(db, record.id),
        edited_by_user_id=actor_user_id,
        change_type=change_type,
        change_reason=change_reason,
        before=before,
        after=after,
    )
    db.add(revision)
    db.flush()
    return revision


def transition(
    db: Session,
    *,
    record: HealthRecord,
    target: VerificationStatus,
    actor: User,
    note: str | None = None,
) -> HealthRecord:
    """Apply a verification transition, enforcing the state machine."""
    if record.status == target:
        raise ConflictError(f"Record is already '{target.value}'.")
    if not can_transition(record.status, target):
        raise ValidationAppError(
            f"Cannot change verification status from '{record.status.value}' "
            f"to '{target.value}'."
        )
    if note and len(note) > 500:
        raise ValidationAppError("Verification note must be 500 characters or fewer.")

    before = snapshot(record)
    record.status = target
    if target == VerificationStatus.VERIFIED:
        record.verified_by_user_id = actor.id
        record.verified_at = datetime.now(UTC)
        record.verification_note = note
    elif target == VerificationStatus.REJECTED:
        record.verified_by_user_id = actor.id
        record.verified_at = datetime.now(UTC)
        record.verification_note = note
    else:
        record.verified_by_user_id = None
        record.verified_at = None
        record.verification_note = note

    db.flush()
    add_revision(
        db,
        record=record,
        before=before,
        after=snapshot(record),
        actor_user_id=actor.id,
        change_type="verification",
        change_reason=note or f"status -> {target.value}",
    )
    return record
