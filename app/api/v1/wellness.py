"""Holistic health endpoints (AYUSH and other care systems)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import NotFoundError, ValidationAppError
from app.core.pagination import paginate
from app.models.document import Document
from app.models.enums import AccessScope, CareSystem, VerificationStatus
from app.models.wellness import WellnessRecord
from app.schemas.common import PageMeta, Paginated
from app.schemas.medication import HerbDrugOverlapOut, HerbDrugOverlapsOut, WellnessCreate, WellnessOut
from app.services import wellness as wellness_service
from app.services.access import require_patient_access, require_patient_write_access
from app.services.audit import record_audit

router = APIRouter(tags=["Wellness (AYUSH)"])

WELLNESS_NOT_FOUND = "Wellness record not found or not accessible."


@router.post(
    "/patients/{patient_id}/wellness",
    response_model=WellnessOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add an AYUSH or other wellness record",
)
def add_wellness_record(
    patient_id: uuid.UUID,
    payload: WellnessCreate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> WellnessRecord:
    require_patient_write_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.WELLNESS,
        request=request,
        action="wellness.create",
    )
    wellness_service.validate_herb_payload([herb.model_dump() for herb in payload.herbs])
    if payload.source_document_id is not None:
        document = db.get(Document, payload.source_document_id)
        if document is None or document.patient_id != patient_id:
            raise ValidationAppError("Source document does not belong to this patient.")

    record = WellnessRecord(
        patient_id=patient_id,
        care_system=payload.care_system,
        record_type=payload.record_type,
        title=payload.title,
        practitioner_name=payload.practitioner_name,
        facility_name=payload.facility_name,
        recorded_at=payload.recorded_at,
        herbs=[herb.model_dump() for herb in payload.herbs],
        formulation_name=payload.formulation_name,
        documented_ingredients=[
            ingredient.model_dump() for ingredient in payload.documented_ingredients
        ],
        notes=payload.notes,
        source_document_id=payload.source_document_id,
        verification_status=VerificationStatus.UNVERIFIED,
        created_by_user_id=user.id,
    )
    db.add(record)
    db.flush()
    record_audit(
        db,
        action="wellness.created",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=patient_id,
        resource_type="wellness_record",
        resource_id=str(record.id),
        request=request,
        context={"care_system": str(record.care_system)},
    )
    return record


@router.get(
    "/patients/{patient_id}/wellness",
    response_model=Paginated[WellnessOut],
    summary="List wellness records, optionally by care system",
)
def list_wellness_records(
    patient_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    page: int = 1,
    page_size: int | None = None,
    care_system: CareSystem | None = None,
) -> Paginated[WellnessOut]:
    require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.WELLNESS,
        request=request,
        action="wellness.list",
    )
    stmt = select(WellnessRecord).where(WellnessRecord.patient_id == patient_id)
    if care_system is not None:
        stmt = stmt.where(WellnessRecord.care_system == care_system)
    stmt = stmt.order_by(WellnessRecord.recorded_at.desc())
    page_result = paginate(db, stmt, page=page, page_size=page_size)
    return Paginated[WellnessOut](
        items=[WellnessOut.model_validate(item) for item in page_result.items],
        meta=PageMeta(**page_result.meta()),
    )


@router.get(
    "/patients/{patient_id}/wellness/checks/herb-drug-overlaps",
    response_model=HerbDrugOverlapsOut,
    summary="Curated herb–drug overlap warnings with evidence and review status",
)
def herb_drug_overlaps(
    patient_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> HerbDrugOverlapsOut:
    require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.WELLNESS,
        request=request,
        action="wellness.overlap_check",
    )
    payload = wellness_service.herb_drug_overlaps(db, patient_id=patient_id)
    return HerbDrugOverlapsOut(
        overlaps=[HerbDrugOverlapOut.model_validate(item) for item in payload["overlaps"]],
        care_systems_evaluated=payload.get("care_systems_evaluated", []),
        note=payload.get("note"),
        disclaimer=payload["disclaimer"],
    )


@router.get(
    "/wellness/{wellness_id}",
    response_model=WellnessOut,
    summary="Read one wellness record",
)
def read_wellness_record(
    wellness_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> WellnessRecord:
    record = db.get(WellnessRecord, wellness_id)
    if record is None:
        raise NotFoundError(WELLNESS_NOT_FOUND)
    require_patient_access(
        db,
        user=user,
        patient_id=record.patient_id,
        scope=AccessScope.WELLNESS,
        request=request,
        action="wellness.view",
    )
    return record
