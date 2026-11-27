"""Unified personal health record services.

Records keep their provenance (source document + extraction + page/span data)
and every mutation is recorded as a revision. Deleting is deliberately not
supported: medical history is append-only at the record level.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ValidationAppError
from app.core.pagination import Page, paginate
from app.models.document import Document, DocumentExtraction
from app.models.enums import RecordCategory, RecordOrigin, VerificationStatus
from app.models.record import HealthRecord
from app.services.verification import add_revision, snapshot

EDITABLE_FIELDS = frozenset(
    {
        "category",
        "title",
        "summary",
        "recorded_at",
        "provider_name",
        "facility_name",
        "provenance",
    }
)


@dataclass(frozen=True)
class RecordFilters:
    category: RecordCategory | None = None
    status: VerificationStatus | None = None
    search: str | None = None
    recorded_from: datetime | None = None
    recorded_to: datetime | None = None
    provider_name: str | None = None
    source_document_id: uuid.UUID | None = None
    has_document: bool | None = None


def _validate_sources(
    db: Session,
    *,
    patient_id: uuid.UUID,
    source_document_id: uuid.UUID | None,
    source_extraction_id: uuid.UUID | None,
) -> None:
    if source_document_id is not None:
        document = db.get(Document, source_document_id)
        if document is None or document.patient_id != patient_id:
            raise ValidationAppError("Source document does not belong to this patient.")
    if source_extraction_id is not None:
        extraction = db.get(DocumentExtraction, source_extraction_id)
        if extraction is None or extraction.patient_id != patient_id:
            raise ValidationAppError("Source extraction does not belong to this patient.")


def create_record(
    db: Session,
    *,
    patient_id: uuid.UUID,
    category: RecordCategory,
    title: str,
    recorded_at: datetime,
    summary: str | None = None,
    provider_name: str | None = None,
    facility_name: str | None = None,
    origin: RecordOrigin = RecordOrigin.USER,
    created_by_user_id: uuid.UUID | None = None,
    status: VerificationStatus = VerificationStatus.UNVERIFIED,
    source_document_id: uuid.UUID | None = None,
    source_extraction_id: uuid.UUID | None = None,
    provenance: dict[str, Any] | None = None,
) -> HealthRecord:
    _validate_sources(
        db,
        patient_id=patient_id,
        source_document_id=source_document_id,
        source_extraction_id=source_extraction_id,
    )
    if origin == RecordOrigin.AI_ENGINE and status == VerificationStatus.VERIFIED:
        # Defence in depth: the AI engine can never assert clinical verification.
        raise ValidationAppError("AI-extracted records cannot be created as verified.")

    record = HealthRecord(
        patient_id=patient_id,
        category=category,
        title=title.strip(),
        summary=summary,
        recorded_at=recorded_at,
        provider_name=provider_name,
        facility_name=facility_name,
        origin=origin,
        created_by_user_id=created_by_user_id,
        status=status,
        source_document_id=source_document_id,
        source_extraction_id=source_extraction_id,
        provenance=provenance or {},
    )
    db.add(record)
    db.flush()
    add_revision(
        db,
        record=record,
        before={},
        after=snapshot(record),
        actor_user_id=created_by_user_id,
        change_type="create",
        change_reason="Record created.",
    )
    return record


def update_record(
    db: Session,
    *,
    record: HealthRecord,
    updates: dict[str, Any],
    actor_user_id: uuid.UUID,
    change_reason: str | None = None,
) -> HealthRecord:
    unknown = set(updates) - EDITABLE_FIELDS
    if unknown:
        raise ValidationAppError(
            "These fields cannot be edited: " + ", ".join(sorted(unknown))
        )
    before = snapshot(record)
    changed = False
    for field, value in updates.items():
        if field == "title" and isinstance(value, str):
            value = value.strip()
        if getattr(record, field) != value:
            setattr(record, field, value)
            changed = True
    if not changed:
        return record
    db.flush()
    add_revision(
        db,
        record=record,
        before=before,
        after=snapshot(record),
        actor_user_id=actor_user_id,
        change_type="edit",
        change_reason=change_reason,
    )
    return record


def _filtered_statement(patient_id: uuid.UUID, filters: RecordFilters) -> Select[Any]:
    stmt = select(HealthRecord).where(HealthRecord.patient_id == patient_id)
    if filters.category is not None:
        stmt = stmt.where(HealthRecord.category == filters.category)
    if filters.status is not None:
        stmt = stmt.where(HealthRecord.status == filters.status)
    if filters.provider_name:
        stmt = stmt.where(HealthRecord.provider_name.ilike(f"%{filters.provider_name}%"))
    if filters.recorded_from is not None:
        stmt = stmt.where(HealthRecord.recorded_at >= filters.recorded_from)
    if filters.recorded_to is not None:
        stmt = stmt.where(HealthRecord.recorded_at <= filters.recorded_to)
    if filters.source_document_id is not None:
        stmt = stmt.where(HealthRecord.source_document_id == filters.source_document_id)
    if filters.has_document is True:
        stmt = stmt.where(HealthRecord.source_document_id.is_not(None))
    if filters.has_document is False:
        stmt = stmt.where(HealthRecord.source_document_id.is_(None))
    if filters.search:
        term = filters.search.strip()
        if term:
            pattern = f"%{term}%"
            stmt = stmt.where(
                or_(
                    HealthRecord.title.ilike(pattern),
                    HealthRecord.summary.ilike(pattern),
                    HealthRecord.provider_name.ilike(pattern),
                    HealthRecord.facility_name.ilike(pattern),
                )
            )
    return stmt.order_by(HealthRecord.recorded_at.desc(), HealthRecord.created_at.desc())


def list_records(
    db: Session,
    *,
    patient_id: uuid.UUID,
    filters: RecordFilters,
    page: int = 1,
    page_size: int | None = None,
) -> Page[HealthRecord]:
    return paginate(
        db, _filtered_statement(patient_id, filters), page=page, page_size=page_size
    )


def timeline(
    db: Session, *, patient_id: uuid.UUID, limit: int = 100
) -> list[dict[str, Any]]:
    """Chronological (newest first) merge of records, measurements and medication starts."""
    from app.models.biomarker import LabResult
    from app.models.medication import Medication

    entries: list[dict[str, Any]] = []
    records = db.scalars(
        select(HealthRecord)
        .where(HealthRecord.patient_id == patient_id)
        .order_by(HealthRecord.recorded_at.desc())
        .limit(limit)
    )
    for record in records:
        entries.append(
            {
                "entry_type": "record",
                "occurred_at": record.recorded_at,
                "title": record.title,
                "category": str(record.category),
                "verification_status": str(record.status),
                "id": str(record.id),
                "source_document_id": str(record.source_document_id)
                if record.source_document_id
                else None,
            }
        )

    results = db.scalars(
        select(LabResult)
        .where(LabResult.patient_id == patient_id)
        .order_by(LabResult.collected_at.desc())
        .limit(limit)
    )
    for result in results:
        entries.append(
            {
                "entry_type": "measurement",
                "occurred_at": result.collected_at,
                "title": f"{result.analyte_display}: {result.original_value_text or result.value_numeric} {result.unit}",
                "category": "biomarker",
                "verification_status": str(result.verification_status),
                "id": str(result.id),
                "source_document_id": str(result.source_document_id)
                if result.source_document_id
                else None,
            }
        )

    meds = db.scalars(
        select(Medication)
        .where(Medication.patient_id == patient_id, Medication.started_on.is_not(None))
        .order_by(Medication.started_on.desc())
        .limit(limit)
    )
    for medication in meds:
        entries.append(
            {
                "entry_type": "medication_start",
                "occurred_at": medication.started_on,
                "title": medication.brand_name
                or medication.generic_name
                or "Medication",
                "category": "medication",
                "verification_status": str(medication.verification_status),
                "id": str(medication.id),
                "source_document_id": str(medication.source_document_id)
                if medication.source_document_id
                else None,
            }
        )

    def sort_key(entry: dict[str, Any]) -> datetime:
        value = entry["occurred_at"]
        if isinstance(value, datetime):
            return value
        # A bare date (medication start) sorts at midnight.
        return datetime(value.year, value.month, value.day, tzinfo=None)

    entries.sort(key=sort_key, reverse=True)
    return entries[:limit]
