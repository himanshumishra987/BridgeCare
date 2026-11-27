"""Patient profile endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import NotFoundError
from app.models.enums import AccessScope
from app.models.patient import PatientProfile
from app.schemas.patient import PatientProfileOut, PatientProfileUpdate
from app.services.access import require_patient_access, require_patient_write_access
from app.services.audit import record_audit

router = APIRouter(prefix="/patients", tags=["Patient profiles"])

NO_PROFILE_MESSAGE = "No patient profile is linked to this account."


def my_profile(db: DbSession, user: CurrentUser) -> PatientProfile:
    profile = db.scalar(select(PatientProfile).where(PatientProfile.user_id == user.id))
    if profile is None:
        raise NotFoundError(NO_PROFILE_MESSAGE)
    return profile


@router.get("/me", response_model=PatientProfileOut, summary="Read my health profile")
def read_my_profile(user: CurrentUser, db: DbSession) -> PatientProfile:
    return my_profile(db, user)


@router.patch("/me", response_model=PatientProfileOut, summary="Update my health profile")
def update_my_profile(
    payload: PatientProfileUpdate, request: Request, user: CurrentUser, db: DbSession
) -> PatientProfile:
    profile = my_profile(db, user)
    require_patient_write_access(
        db,
        user=user,
        patient_id=profile.id,
        scope=AccessScope.DEMOGRAPHICS,
        request=request,
        action="profile.update",
    )
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(profile, field, value)
    db.flush()
    record_audit(
        db,
        action="profile.updated",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=profile.id,
        resource_type="patient_profile",
        resource_id=str(profile.id),
        request=request,
        context={"fields": sorted(updates)},
    )
    return profile


@router.get(
    "/{patient_id}",
    response_model=PatientProfileOut,
    summary="Read a profile I have been granted access to",
)
def read_profile(
    patient_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> PatientProfile:
    ctx = require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.DEMOGRAPHICS,
        request=request,
        action="profile.view",
    )
    record_audit(
        db,
        action="profile.viewed",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=ctx.patient.id,
        resource_type="patient_profile",
        resource_id=str(ctx.patient.id),
        request=request,
        context={"basis": ctx.basis},
    )
    return ctx.patient
