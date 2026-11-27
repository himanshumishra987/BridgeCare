"""Verified-record context for the AI engine.

Only records a human has explicitly moved to ``VERIFIED`` may leave the backend
for assistant or summary generation. Unverified, pending-review and rejected
rows are excluded, so an AI proposal can never be echoed back as clinical fact.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models.enums import VerificationStatus
from app.models.patient import PatientProfile
from app.models.record import HealthRecord

DEFAULT_CONTEXT_RECORDS = 50
MAX_CONTEXT_RECORDS = 200
PATIENT_NOT_FOUND = "Patient profile not found."


@dataclass(frozen=True)
class PatientContext:
    patient: PatientProfile
    records: list[HealthRecord]


def verified_record_context(
    db: Session, *, patient_id: uuid.UUID, limit: int = DEFAULT_CONTEXT_RECORDS
) -> PatientContext:
    """Return the patient and their verified records, newest first."""
    patient = db.get(PatientProfile, patient_id)
    if patient is None:
        raise NotFoundError(PATIENT_NOT_FOUND)
    capped = max(1, min(limit, MAX_CONTEXT_RECORDS))
    records = list(
        db.scalars(
            select(HealthRecord)
            .where(
                HealthRecord.patient_id == patient_id,
                HealthRecord.status == VerificationStatus.VERIFIED,
            )
            .order_by(HealthRecord.recorded_at.desc(), HealthRecord.created_at.desc())
            .limit(capped)
        )
    )
    return PatientContext(patient=patient, records=records)
