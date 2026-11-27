"""Unified personal health record endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import NotFoundError
from app.core.pagination import paginate
from app.models.enums import AccessScope, RecordCategory, VerificationStatus
from app.models.record import HealthRecord, RecordRevision
from app.schemas.clinical import (
    RecordCreate,
    RecordOut,
    RecordRevisionOut,
    RecordUpdate,
    RecordVerifyRequest,
    TimelineEntryOut,
)
from app.schemas.common import PageMeta, Paginated
from app.services.access import (
    require_patient_access,
    require_patient_write_access,
    require_record_verifier,
)
from app.services.audit import record_audit
from app.services.records import RecordFilters, create_record, list_records, timeline, update_record
from app.services.verification import transition

router = APIRouter(tags=["Health records"])

RECORD_NOT_FOUND = "Record not found or not accessible."


def _load_record(db: DbSession, record_id: uuid.UUID) -> HealthRecord:
    record = db.get(HealthRecord, record_id)
    if record is None:
        raise NotFoundError(RECORD_NOT_FOUND)
    return record


@router.post(
    "/patients/{patient_id}/records",
    response_model=RecordOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a structured health record",
)
def add_record(
    patient_id: uuid.UUID,
    payload: RecordCreate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> HealthRecord:
    require_patient_write_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.RECORDS,
        request=request,
        action="record.create",
    )
    record = create_record(
        db,
        patient_id=patient_id,
        category=payload.category,
        title=payload.title,
        recorded_at=payload.recorded_at,
        summary=payload.summary,
        provider_name=payload.provider_name,
        facility_name=payload.facility_name,
        created_by_user_id=user.id,
        source_document_id=payload.source_document_id,
        provenance=payload.provenance,
    )
    record_audit(
        db,
        action="record.created",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=patient_id,
        resource_type="health_record",
        resource_id=str(record.id),
        request=request,
        context={"category": str(record.category)},
    )
    return record


@router.get(
    "/patients/{patient_id}/records",
    response_model=Paginated[RecordOut],
    summary="Search and filter records (newest first)",
)
def search_records(
    patient_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    page: int = 1,
    page_size: int | None = None,
    category: RecordCategory | None = None,
    status_filter: VerificationStatus | None = None,
    q: str | None = None,
    recorded_from: datetime | None = None,
    recorded_to: datetime | None = None,
    provider: str | None = None,
    has_document: bool | None = None,
) -> Paginated[RecordOut]:
    require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.RECORDS,
        request=request,
        action="record.list",
    )
    filters = RecordFilters(
        category=category,
        status=status_filter,
        search=q,
        recorded_from=recorded_from,
        recorded_to=recorded_to,
        provider_name=provider,
        has_document=has_document,
    )
    page_result = list_records(
        db, patient_id=patient_id, filters=filters, page=page, page_size=page_size
    )
    return Paginated[RecordOut](
        items=[RecordOut.model_validate(item) for item in page_result.items],
        meta=PageMeta(**page_result.meta()),
    )


@router.get(
    "/patients/{patient_id}/records/timeline",
    response_model=list[TimelineEntryOut],
    summary="Chronological timeline of records, measurements and medication starts",
)
def read_timeline(
    patient_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    limit: int = 100,
) -> list[TimelineEntryOut]:
    require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.RECORDS,
        request=request,
        action="record.timeline",
    )
    entries = timeline(db, patient_id=patient_id, limit=max(1, min(limit, 500)))
    return [TimelineEntryOut.model_validate(entry) for entry in entries]


@router.get("/records/{record_id}", response_model=RecordOut, summary="Read one record")
def read_record(
    record_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> HealthRecord:
    record = _load_record(db, record_id)
    require_patient_access(
        db,
        user=user,
        patient_id=record.patient_id,
        scope=AccessScope.RECORDS,
        request=request,
        action="record.view",
    )
    return record


@router.patch(
    "/records/{record_id}",
    response_model=RecordOut,
    summary="Edit a record (creates an immutable revision)",
)
def edit_record(
    record_id: uuid.UUID,
    payload: RecordUpdate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> HealthRecord:
    record = _load_record(db, record_id)
    require_patient_write_access(
        db,
        user=user,
        patient_id=record.patient_id,
        scope=AccessScope.RECORDS,
        request=request,
        action="record.update",
    )
    updates = payload.model_dump(exclude_unset=True)
    change_reason = updates.pop("change_reason", None)
    update_record(
        db,
        record=record,
        updates=updates,
        actor_user_id=user.id,
        change_reason=change_reason,
    )
    record_audit(
        db,
        action="record.updated",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=record.patient_id,
        resource_type="health_record",
        resource_id=str(record.id),
        request=request,
        context={"fields": sorted(updates)},
    )
    return record


@router.post(
    "/records/{record_id}/verify",
    response_model=RecordOut,
    summary="Human verification decision (owner, guardian or granted clinician)",
)
def verify_record(
    record_id: uuid.UUID,
    payload: RecordVerifyRequest,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> HealthRecord:
    record = _load_record(db, record_id)
    require_record_verifier(db, user=user, patient=record_patient(db, record), request=request)
    target = VerificationStatus(payload.status)
    transition(db, record=record, target=target, actor=user, note=payload.note)
    record_audit(
        db,
        action=f"record.{target.value}",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=record.patient_id,
        resource_type="health_record",
        resource_id=str(record.id),
        request=request,
    )
    return record


def record_patient(db: DbSession, record: HealthRecord):
    from app.models.patient import PatientProfile

    patient = db.get(PatientProfile, record.patient_id)
    if patient is None:
        raise NotFoundError(RECORD_NOT_FOUND)
    return patient


@router.get(
    "/records/{record_id}/revisions",
    response_model=list[RecordRevisionOut],
    summary="Read the append-only edit and verification history",
)
def list_revisions(
    record_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> list[RecordRevisionOut]:
    record = _load_record(db, record_id)
    require_patient_access(
        db,
        user=user,
        patient_id=record.patient_id,
        scope=AccessScope.RECORDS,
        request=request,
        action="record.revisions",
    )
    rows = db.scalars(
        select(RecordRevision)
        .where(RecordRevision.record_id == record.id)
        .order_by(RecordRevision.revision_number.asc())
    )
    return [RecordRevisionOut.model_validate(row) for row in rows]
