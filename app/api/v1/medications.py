"""Medication, schedule, reminder and medication-safety endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import NotFoundError, ValidationAppError
from app.core.pagination import paginate
from app.models.emergency import Reminder
from app.models.enums import AccessScope, MedicationStatus
from app.models.medication import Medication, MedicationSchedule
from app.models.record import HealthRecord
from app.schemas.common import PageMeta, Paginated, OkResponse
from app.schemas.medication import (
    DuplicateGroupOut,
    InteractionWarningOut,
    InteractionWarningsOut,
    MedicationCreate,
    MedicationOut,
    MedicationRefOut,
    MedicationScheduleCreate,
    MedicationScheduleOut,
    MedicationStopRequest,
    MedicationUpdate,
    OverlapSideOut,
    PrescriptionOverlapOut,
    ReminderCreate,
    ReminderOut,
    ReminderUpdate,
)
from app.services import medications as medication_service
from app.services.access import require_patient_access, require_patient_write_access
from app.services.audit import record_audit

router = APIRouter(tags=["Medications"])

MEDICATION_NOT_FOUND = "Medication not found or not accessible."
REMINDER_NOT_FOUND = "Reminder not found or not accessible."


def _load_medication(db: DbSession, medication_id: uuid.UUID) -> Medication:
    medication = db.get(Medication, medication_id)
    if medication is None:
        raise NotFoundError(MEDICATION_NOT_FOUND)
    return medication


@router.post(
    "/patients/{patient_id}/medications",
    response_model=MedicationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a medication as recorded (no dosage is ever generated)",
)
def add_medication(
    patient_id: uuid.UUID,
    payload: MedicationCreate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> Medication:
    require_patient_write_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.MEDICATIONS,
        request=request,
        action="medication.create",
    )
    if payload.source_record_id is not None:
        record = db.get(HealthRecord, payload.source_record_id)
        if record is None or record.patient_id != patient_id:
            raise ValidationAppError("Source record does not belong to this patient.")

    medication = Medication(
        patient_id=patient_id,
        brand_name=payload.brand_name,
        generic_name=payload.generic_name,
        active_ingredients=[item.model_dump() for item in payload.active_ingredients],
        form=payload.form,
        route=payload.route,
        status=payload.status,
        started_on=payload.started_on,
        ended_on=payload.ended_on,
        prescribed_by=payload.prescribed_by,
        dose_text=payload.dose_text,
        indication=payload.indication,
        notes=payload.notes,
        source_record_id=payload.source_record_id,
        created_by_user_id=user.id,
    )
    db.add(medication)
    db.flush()
    record_audit(
        db,
        action="medication.created",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=patient_id,
        resource_type="medication",
        resource_id=str(medication.id),
        request=request,
    )
    return medication


@router.get(
    "/patients/{patient_id}/medications",
    response_model=Paginated[MedicationOut],
    summary="Medication history",
)
def list_medications(
    patient_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    page: int = 1,
    page_size: int | None = None,
    status_filter: MedicationStatus | None = None,
) -> Paginated[MedicationOut]:
    require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.MEDICATIONS,
        request=request,
        action="medication.list",
    )
    stmt = select(Medication).where(Medication.patient_id == patient_id)
    if status_filter is not None:
        stmt = stmt.where(Medication.status == status_filter)
    stmt = stmt.order_by(Medication.started_on.desc().nullslast(), Medication.created_at.desc())
    page_result = paginate(db, stmt, page=page, page_size=page_size)
    return Paginated[MedicationOut](
        items=[MedicationOut.model_validate(item) for item in page_result.items],
        meta=PageMeta(**page_result.meta()),
    )


@router.get(
    "/patients/{patient_id}/medications/checks/duplicate-ingredients",
    response_model=list[DuplicateGroupOut],
    summary="Active medications sharing an active ingredient",
)
def duplicate_ingredients(
    patient_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> list[DuplicateGroupOut]:
    require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.MEDICATIONS,
        request=request,
        action="medication.duplicate_check",
    )
    groups = medication_service.duplicate_ingredients(db, patient_id=patient_id)
    return [
        DuplicateGroupOut(
            ingredient_key=group.ingredient_key,
            medications=[MedicationRefOut(**item) for item in group.medications],
        )
        for group in groups
    ]


@router.get(
    "/patients/{patient_id}/medications/checks/overlaps",
    response_model=list[PrescriptionOverlapOut],
    summary="Overlapping prescription periods for the same ingredient",
)
def overlapping_prescriptions(
    patient_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> list[PrescriptionOverlapOut]:
    require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.MEDICATIONS,
        request=request,
        action="medication.overlap_check",
    )
    return [
        PrescriptionOverlapOut(
            ingredient_keys=item["ingredient_keys"],
            overlap_start=item["overlap_start"],
            overlap_end=item["overlap_end"],
            left=OverlapSideOut(**item["left"]),
            right=OverlapSideOut(**item["right"]),
        )
        for item in medication_service.overlapping_prescriptions(db, patient_id=patient_id)
    ]


@router.get(
    "/patients/{patient_id}/medications/checks/interaction-warnings",
    response_model=InteractionWarningsOut,
    summary="Curated interaction warnings with citations and review status",
)
def interaction_warnings(
    patient_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> InteractionWarningsOut:
    require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.MEDICATIONS,
        request=request,
        action="medication.interaction_check",
    )
    payload = medication_service.interaction_warnings(db, patient_id=patient_id)
    return InteractionWarningsOut(
        warnings=[InteractionWarningOut.model_validate(item) for item in payload["warnings"]],
        rules_reviewed=payload["rules_reviewed"],
        disclaimer=payload["disclaimer"],
    )


@router.get(
    "/medications/{medication_id}",
    response_model=MedicationOut,
    summary="Read one medication",
)
def read_medication(
    medication_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> Medication:
    medication = _load_medication(db, medication_id)
    require_patient_access(
        db,
        user=user,
        patient_id=medication.patient_id,
        scope=AccessScope.MEDICATIONS,
        request=request,
        action="medication.view",
    )
    return medication


@router.patch(
    "/medications/{medication_id}",
    response_model=MedicationOut,
    summary="Update a medication record",
)
def edit_medication(
    medication_id: uuid.UUID,
    payload: MedicationUpdate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> Medication:
    medication = _load_medication(db, medication_id)
    require_patient_write_access(
        db,
        user=user,
        patient_id=medication.patient_id,
        scope=AccessScope.MEDICATIONS,
        request=request,
        action="medication.update",
    )
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(medication, field, value)
    if medication.started_on and medication.ended_on and medication.ended_on < medication.started_on:
        raise ValidationAppError("ended_on must not precede started_on.")
    db.flush()
    record_audit(
        db,
        action="medication.updated",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=medication.patient_id,
        resource_type="medication",
        resource_id=str(medication.id),
        request=request,
        context={"fields": sorted(updates)},
    )
    return medication


@router.post(
    "/medications/{medication_id}/stop",
    response_model=MedicationOut,
    summary="Mark a medication as stopped (records the date; gives no advice)",
)
def stop_medication(
    medication_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    payload: MedicationStopRequest | None = None,
) -> Medication:
    medication = _load_medication(db, medication_id)
    require_patient_write_access(
        db,
        user=user,
        patient_id=medication.patient_id,
        scope=AccessScope.MEDICATIONS,
        request=request,
        action="medication.stop",
    )
    body = payload or MedicationStopRequest()
    medication.status = MedicationStatus.STOPPED
    medication.ended_on = body.ended_on or datetime.now(UTC).date()
    if medication.notes is None and body.reason:
        medication.notes = body.reason
    db.flush()
    record_audit(
        db,
        action="medication.stopped",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=medication.patient_id,
        resource_type="medication",
        resource_id=str(medication.id),
        request=request,
    )
    return medication


@router.post(
    "/medications/{medication_id}/schedules",
    response_model=MedicationScheduleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a recorded dosing schedule",
)
def add_schedule(
    medication_id: uuid.UUID,
    payload: MedicationScheduleCreate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> MedicationSchedule:
    medication = _load_medication(db, medication_id)
    require_patient_write_access(
        db,
        user=user,
        patient_id=medication.patient_id,
        scope=AccessScope.MEDICATIONS,
        request=request,
        action="medication.schedule.create",
    )
    schedule = MedicationSchedule(
        medication_id=medication.id,
        patient_id=medication.patient_id,
        frequency=payload.frequency,
        times=payload.times,
        timezone=payload.timezone,
        start_date=payload.start_date,
        end_date=payload.end_date,
        instructions_text=payload.instructions_text,
    )
    db.add(schedule)
    db.flush()
    record_audit(
        db,
        action="medication.schedule.created",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=medication.patient_id,
        resource_type="medication_schedule",
        resource_id=str(schedule.id),
        request=request,
    )
    return schedule


@router.get(
    "/medications/{medication_id}/schedules",
    response_model=list[MedicationScheduleOut],
    summary="List schedules for a medication",
)
def list_schedules(
    medication_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> list[MedicationScheduleOut]:
    medication = _load_medication(db, medication_id)
    require_patient_access(
        db,
        user=user,
        patient_id=medication.patient_id,
        scope=AccessScope.MEDICATIONS,
        request=request,
        action="medication.schedule.list",
    )
    rows = db.scalars(
        select(MedicationSchedule)
        .where(MedicationSchedule.medication_id == medication.id)
        .order_by(MedicationSchedule.created_at.desc())
    )
    return [MedicationScheduleOut.model_validate(row) for row in rows]


@router.post(
    "/patients/{patient_id}/reminders",
    response_model=ReminderOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a reminder (medication, appointment, checkup)",
)
def add_reminder(
    patient_id: uuid.UUID,
    payload: ReminderCreate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> Reminder:
    require_patient_write_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.MEDICATIONS,
        request=request,
        action="reminder.create",
    )
    if payload.medication_schedule_id is not None:
        schedule = db.get(MedicationSchedule, payload.medication_schedule_id)
        if schedule is None or schedule.patient_id != patient_id:
            raise ValidationAppError("Schedule does not belong to this patient.")
    reminder = Reminder(
        patient_id=patient_id,
        kind=payload.kind,
        title=payload.title,
        notes=payload.notes,
        due_at=payload.due_at,
        recurrence=payload.recurrence,
        timezone=payload.timezone,
        channel=payload.channel,
        medication_schedule_id=payload.medication_schedule_id,
        created_by_user_id=user.id,
    )
    db.add(reminder)
    db.flush()
    record_audit(
        db,
        action="reminder.created",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=patient_id,
        resource_type="reminder",
        resource_id=str(reminder.id),
        request=request,
    )
    return reminder


@router.get(
    "/patients/{patient_id}/reminders",
    response_model=Paginated[ReminderOut],
    summary="List reminders by due date",
)
def list_reminders(
    patient_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    page: int = 1,
    page_size: int | None = None,
    enabled_only: bool = False,
) -> Paginated[ReminderOut]:
    require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.MEDICATIONS,
        request=request,
        action="reminder.list",
    )
    stmt = select(Reminder).where(Reminder.patient_id == patient_id)
    if enabled_only:
        stmt = stmt.where(Reminder.is_enabled.is_(True))
    stmt = stmt.order_by(Reminder.due_at.asc())
    page_result = paginate(db, stmt, page=page, page_size=page_size)
    return Paginated[ReminderOut](
        items=[ReminderOut.model_validate(item) for item in page_result.items],
        meta=PageMeta(**page_result.meta()),
    )


def _load_reminder(db: DbSession, reminder_id: uuid.UUID) -> Reminder:
    reminder = db.get(Reminder, reminder_id)
    if reminder is None:
        raise NotFoundError(REMINDER_NOT_FOUND)
    return reminder


@router.patch(
    "/reminders/{reminder_id}",
    response_model=ReminderOut,
    summary="Update or disable a reminder",
)
def edit_reminder(
    reminder_id: uuid.UUID,
    payload: ReminderUpdate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> Reminder:
    reminder = _load_reminder(db, reminder_id)
    require_patient_write_access(
        db,
        user=user,
        patient_id=reminder.patient_id,
        scope=AccessScope.MEDICATIONS,
        request=request,
        action="reminder.update",
    )
    updates = payload.model_dump(exclude_unset=True)
    completed = updates.pop("completed", None)
    for field, value in updates.items():
        setattr(reminder, field, value)
    if completed is True:
        reminder.completed_at = datetime.now(UTC)
    elif completed is False:
        reminder.completed_at = None
    db.flush()
    record_audit(
        db,
        action="reminder.updated",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=reminder.patient_id,
        resource_type="reminder",
        resource_id=str(reminder.id),
        request=request,
    )
    return reminder


@router.post(
    "/reminders/{reminder_id}/acknowledge",
    response_model=ReminderOut,
    summary="Acknowledge a reminder as seen",
)
def acknowledge_reminder(
    reminder_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> Reminder:
    reminder = _load_reminder(db, reminder_id)
    require_patient_write_access(
        db,
        user=user,
        patient_id=reminder.patient_id,
        scope=AccessScope.MEDICATIONS,
        request=request,
        action="reminder.acknowledge",
    )
    reminder.acknowledged_at = datetime.now(UTC)
    db.flush()
    return reminder


@router.delete(
    "/reminders/{reminder_id}",
    response_model=OkResponse,
    summary="Delete a reminder",
)
def delete_reminder(
    reminder_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> OkResponse:
    reminder = _load_reminder(db, reminder_id)
    require_patient_write_access(
        db,
        user=user,
        patient_id=reminder.patient_id,
        scope=AccessScope.MEDICATIONS,
        request=request,
        action="reminder.delete",
    )
    db.delete(reminder)
    db.flush()
    record_audit(
        db,
        action="reminder.deleted",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=reminder.patient_id,
        resource_type="reminder",
        resource_id=str(reminder.id),
        request=request,
    )
    return OkResponse()
