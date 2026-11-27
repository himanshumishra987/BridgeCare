"""Emergency contacts, authorized emergency summary and hospital discovery."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import NotFoundError, ServiceUnavailableError
from app.models.emergency import EmergencyContact
from app.models.enums import AccessScope
from app.schemas.common import OkResponse
from app.schemas.emergency import (
    EmergencyContactCreate,
    EmergencyContactOut,
    EmergencyContactUpdate,
    EmergencySummaryOut,
    HospitalSearchOut,
)
from app.services.access import require_patient_access, require_patient_write_access
from app.services.audit import record_audit
from app.services.emergency import build_emergency_summary, nearby_hospitals

router = APIRouter(tags=["Emergency support"])

CONTACT_NOT_FOUND = "Emergency contact not found."


@router.get(
    "/patients/{patient_id}/emergency/contacts",
    response_model=list[EmergencyContactOut],
    summary="List emergency contacts",
)
def list_contacts(
    patient_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> list[EmergencyContactOut]:
    require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.EMERGENCY,
        request=request,
        action="emergency.contacts.list",
    )
    rows = db.scalars(
        select(EmergencyContact)
        .where(EmergencyContact.patient_id == patient_id)
        .order_by(EmergencyContact.is_primary.desc(), EmergencyContact.name.asc())
    )
    return [EmergencyContactOut.model_validate(row) for row in rows]


@router.post(
    "/patients/{patient_id}/emergency/contacts",
    response_model=EmergencyContactOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add an emergency contact",
)
def add_contact(
    patient_id: uuid.UUID,
    payload: EmergencyContactCreate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> EmergencyContact:
    require_patient_write_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.EMERGENCY,
        request=request,
        action="emergency.contact.create",
    )
    contact = EmergencyContact(
        patient_id=patient_id,
        name=payload.name,
        relationship=payload.relationship,
        phone=payload.phone,
        alternate_phone=payload.alternate_phone,
        email=str(payload.email) if payload.email else None,
        is_primary=payload.is_primary,
        notes=payload.notes,
    )
    db.add(contact)
    db.flush()
    record_audit(
        db,
        action="emergency.contact_added",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=patient_id,
        resource_type="emergency_contact",
        resource_id=str(contact.id),
        request=request,
    )
    return contact


def _load_contact(db: DbSession, contact_id: uuid.UUID) -> EmergencyContact:
    contact = db.get(EmergencyContact, contact_id)
    if contact is None:
        raise NotFoundError(CONTACT_NOT_FOUND)
    return contact


@router.patch(
    "/emergency/contacts/{contact_id}",
    response_model=EmergencyContactOut,
    summary="Update an emergency contact",
)
def update_contact(
    contact_id: uuid.UUID,
    payload: EmergencyContactUpdate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> EmergencyContact:
    contact = _load_contact(db, contact_id)
    require_patient_write_access(
        db,
        user=user,
        patient_id=contact.patient_id,
        scope=AccessScope.EMERGENCY,
        request=request,
        action="emergency.contact.update",
    )
    updates = payload.model_dump(exclude_unset=True)
    if "email" in updates and updates["email"] is not None:
        updates["email"] = str(updates["email"])
    for field, value in updates.items():
        setattr(contact, field, value)
    db.flush()
    return contact


@router.delete(
    "/emergency/contacts/{contact_id}",
    response_model=OkResponse,
    summary="Delete an emergency contact",
)
def delete_contact(
    contact_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> OkResponse:
    contact = _load_contact(db, contact_id)
    require_patient_write_access(
        db,
        user=user,
        patient_id=contact.patient_id,
        scope=AccessScope.EMERGENCY,
        request=request,
        action="emergency.contact.delete",
    )
    patient_id = contact.patient_id
    db.delete(contact)
    db.flush()
    record_audit(
        db,
        action="emergency.contact_deleted",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=patient_id,
        resource_type="emergency_contact",
        resource_id=str(contact_id),
        request=request,
    )
    return OkResponse()


@router.get(
    "/patients/{patient_id}/emergency/summary",
    response_model=EmergencySummaryOut,
    summary="Authorized emergency summary (every access is audited)",
)
def emergency_summary(
    patient_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> EmergencySummaryOut:
    ctx = require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.EMERGENCY,
        request=request,
        action="emergency.summary.denied",
    )
    payload = build_emergency_summary(db, patient=ctx.patient)
    payload["access_scope"] = ctx.basis
    record_audit(
        db,
        action="emergency.summary_accessed",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=patient_id,
        resource_type="emergency_summary",
        resource_id=str(patient_id),
        request=request,
        context={"basis": ctx.basis, "consent_id": str(ctx.consent_id) if ctx.consent_id else None},
    )
    return EmergencySummaryOut.model_validate(payload)


@router.get(
    "/emergency/hospitals/nearby",
    response_model=HospitalSearchOut,
    summary="Nearby hospital discovery integration point",
)
def hospitals_nearby(
    user: CurrentUser,
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(10.0, ge=1, le=100),
) -> HospitalSearchOut:
    del user  # any authenticated user may look up facilities; no patient data involved
    try:
        result = nearby_hospitals(latitude=latitude, longitude=longitude, radius_km=radius_km)
    except NotImplementedError as exc:
        raise ServiceUnavailableError(str(exc)) from exc
    return HospitalSearchOut(
        provider=result.provider,
        provider_configured=result.provider_configured,
        hospitals=result.hospitals,
        note=result.note,
    )
