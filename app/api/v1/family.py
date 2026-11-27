"""Family health management and consent endpoints.

Relationship alone never grants access: adding a dependant creates an explicit,
audited guardianship grant, and every other family member needs a patient consent
grant the grantee must accept.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.models.consent import ConsentGrant
from app.models.enums import (
    AccessScope,
    AuditOutcome,
    ConsentBasis,
    ConsentStatus,
    UserRole,
)
from app.models.patient import FamilyMember, PatientProfile
from app.models.user import User
from app.schemas.common import OkResponse
from app.schemas.patient import (
    ConsentCreate,
    ConsentOut,
    ConsentRevokeRequest,
    ConsentWithPatientOut,
    FamilyMemberCreate,
    FamilyMemberOut,
    PatientProfileSummary,
)
from app.services.access import get_patient_or_404, require_consent_manager
from app.services.audit import record_audit

router = APIRouter(tags=["Family & consent"])

MEMBER_NOT_FOUND = "Family member not found."
CONSENT_NOT_FOUND = "Consent grant not found."


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _member_out(db: DbSession, member: FamilyMember) -> FamilyMemberOut:
    profile = db.get(PatientProfile, member.profile_id)
    if profile is None:
        raise NotFoundError(MEMBER_NOT_FOUND)
    return FamilyMemberOut(
        id=member.id,
        relationship=member.relationship,
        is_dependent=member.is_dependent,
        notes=member.notes,
        created_at=member.created_at,
        profile=PatientProfileSummary.model_validate(profile),
    )


@router.get(
    "/family/members",
    response_model=list[FamilyMemberOut],
    summary="List family profiles I manage",
)
def list_family_members(user: CurrentUser, db: DbSession) -> list[FamilyMemberOut]:
    members = db.scalars(
        select(FamilyMember)
        .where(FamilyMember.owner_user_id == user.id)
        .order_by(FamilyMember.created_at.asc())
    )
    return [_member_out(db, member) for member in members]


@router.post(
    "/family/members",
    response_model=FamilyMemberOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a dependant profile with an attested guardianship grant",
)
def add_family_member(
    payload: FamilyMemberCreate, request: Request, user: CurrentUser, db: DbSession
) -> FamilyMemberOut:
    profile = PatientProfile(
        user_id=None,
        display_name=payload.display_name.strip(),
        date_of_birth=payload.date_of_birth,
        sex_at_birth=payload.sex_at_birth,
        blood_group=payload.blood_group,
        primary_language="en",
    )
    db.add(profile)
    db.flush()

    member = FamilyMember(
        owner_user_id=user.id,
        profile_id=profile.id,
        relationship=payload.relationship,
        is_dependent=payload.is_dependent,
        notes=payload.notes,
    )
    db.add(member)
    db.flush()

    db.add(
        ConsentGrant(
            patient_id=profile.id,
            grantee_user_id=user.id,
            granted_by_user_id=user.id,
            scopes=[scope.value for scope in AccessScope],
            purpose="guardianship",
            basis=ConsentBasis.GUARDIANSHIP,
            status=ConsentStatus.ACTIVE,
            accepted_at=_now(),
        )
    )
    db.flush()
    record_audit(
        db,
        action="family.member_added",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=profile.id,
        resource_type="family_member",
        resource_id=str(member.id),
        request=request,
        context={
            "relationship": str(payload.relationship),
            "guardianship_attested": payload.guardianship_attested,
        },
    )
    return _member_out(db, member)


@router.delete(
    "/family/members/{member_id}",
    response_model=OkResponse,
    summary="Remove a family link and revoke my guardianship grant",
)
def remove_family_member(
    member_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> OkResponse:
    member = db.get(FamilyMember, member_id)
    if member is None or member.owner_user_id != user.id:
        raise NotFoundError(MEMBER_NOT_FOUND)

    grants = db.scalars(
        select(ConsentGrant).where(
            ConsentGrant.patient_id == member.profile_id,
            ConsentGrant.grantee_user_id == user.id,
            ConsentGrant.basis == ConsentBasis.GUARDIANSHIP,
            ConsentGrant.status == ConsentStatus.ACTIVE,
        )
    )
    for grant in grants:
        grant.status = ConsentStatus.REVOKED
        grant.revoked_at = _now()
        grant.revoked_by_user_id = user.id
        grant.revoked_reason = "family_member_removed"
    patient_id = member.profile_id
    db.delete(member)
    db.flush()
    record_audit(
        db,
        action="family.member_removed",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=patient_id,
        resource_type="family_member",
        resource_id=str(member_id),
        request=request,
        context={"profile_retained": True},
    )
    return OkResponse()


@router.post(
    "/patients/{patient_id}/consents",
    response_model=ConsentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Grant a caregiver scoped access (grantee must accept)",
)
def grant_consent(
    patient_id: uuid.UUID,
    payload: ConsentCreate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> ConsentGrant:
    patient = get_patient_or_404(db, patient_id)
    require_consent_manager(db, user=user, patient=patient, request=request)

    grantee = db.scalar(
        select(User).where(User.email == str(payload.grantee_email).strip().lower())
    )
    if grantee is None:
        raise ValidationAppError(
            "No BridgeCare account uses that email address. Ask them to register first."
        )
    if grantee.id == user.id:
        raise ValidationAppError("You cannot grant consent to yourself.")
    if patient.user_id == grantee.id:
        raise ConflictError("That account already owns this health record.")

    if payload.expires_at is not None:
        expires_at = _aware(payload.expires_at)
        if expires_at is not None and expires_at <= _now():
            raise ValidationAppError("Expiry must be in the future.")
    else:
        expires_at = None

    existing = db.scalars(
        select(ConsentGrant).where(
            ConsentGrant.patient_id == patient.id,
            ConsentGrant.grantee_user_id == grantee.id,
            ConsentGrant.status.in_([ConsentStatus.PENDING, ConsentStatus.ACTIVE]),
        )
    )
    for grant in existing:
        if grant.status == ConsentStatus.ACTIVE and _aware(grant.expires_at) is None:
            raise ConflictError("An active consent grant already exists for this person.")
        if grant.status == ConsentStatus.ACTIVE:
            if _aware(grant.expires_at) > _now():
                raise ConflictError("An active consent grant already exists for this person.")
        if grant.status == ConsentStatus.PENDING:
            raise ConflictError("A pending consent invitation already exists for this person.")

    grant = ConsentGrant(
        patient_id=patient.id,
        grantee_user_id=grantee.id,
        granted_by_user_id=user.id,
        scopes=[scope.value for scope in payload.scopes],
        purpose=payload.purpose,
        basis=ConsentBasis.PATIENT_CONSENT,
        status=ConsentStatus.PENDING,
        expires_at=expires_at,
    )
    db.add(grant)
    db.flush()
    record_audit(
        db,
        action="consent.granted_pending",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=patient.id,
        resource_type="consent_grant",
        resource_id=str(grant.id),
        request=request,
        context={"scopes": grant.scopes, "expires_at": expires_at.isoformat() if expires_at else None},
    )
    return grant


@router.get(
    "/patients/{patient_id}/consents",
    response_model=list[ConsentOut],
    summary="Consent grants on a patient record",
)
def list_consents(
    patient_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> list[ConsentOut]:
    patient = get_patient_or_404(db, patient_id)
    require_consent_manager(db, user=user, patient=patient, request=request)
    rows = db.scalars(
        select(ConsentGrant)
        .where(ConsentGrant.patient_id == patient.id)
        .order_by(ConsentGrant.created_at.desc())
    )
    return [ConsentOut.model_validate(row) for row in rows]


@router.get(
    "/consents/pending",
    response_model=list[ConsentWithPatientOut],
    summary="Consent invitations awaiting my acceptance",
)
def list_pending_consents(user: CurrentUser, db: DbSession) -> list[ConsentWithPatientOut]:
    rows = db.scalars(
        select(ConsentGrant)
        .where(
            ConsentGrant.grantee_user_id == user.id,
            ConsentGrant.status == ConsentStatus.PENDING,
        )
        .order_by(ConsentGrant.created_at.desc())
    )
    result: list[ConsentWithPatientOut] = []
    for grant in rows:
        if _aware(grant.expires_at) is not None and _aware(grant.expires_at) <= _now():
            continue
        patient = db.get(PatientProfile, grant.patient_id)
        if patient is None:
            continue
        payload = ConsentOut.model_validate(grant).model_dump()
        result.append(
            ConsentWithPatientOut(
                **payload, patient_display_name=patient.display_name
            )
        )
    return result


@router.get(
    "/consents/granted",
    response_model=list[ConsentWithPatientOut],
    summary="Records I currently have access to",
)
def list_granted_consents(user: CurrentUser, db: DbSession) -> list[ConsentWithPatientOut]:
    rows = db.scalars(
        select(ConsentGrant)
        .where(
            ConsentGrant.grantee_user_id == user.id,
            ConsentGrant.status == ConsentStatus.ACTIVE,
        )
        .order_by(ConsentGrant.created_at.desc())
    )
    result: list[ConsentWithPatientOut] = []
    for grant in rows:
        expiry = _aware(grant.expires_at)
        if expiry is not None and expiry <= _now():
            continue
        patient = db.get(PatientProfile, grant.patient_id)
        if patient is None:
            continue
        payload = ConsentOut.model_validate(grant).model_dump()
        result.append(
            ConsentWithPatientOut(**payload, patient_display_name=patient.display_name)
        )
    return result


def _load_grant(db: DbSession, consent_id: uuid.UUID) -> ConsentGrant:
    grant = db.get(ConsentGrant, consent_id)
    if grant is None:
        raise NotFoundError(CONSENT_NOT_FOUND)
    return grant


@router.post(
    "/consents/{consent_id}/accept",
    response_model=ConsentOut,
    summary="Accept a consent invitation (grantee only)",
)
def accept_consent(
    consent_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> ConsentGrant:
    grant = _load_grant(db, consent_id)
    if grant.grantee_user_id != user.id:
        raise NotFoundError(CONSENT_NOT_FOUND)
    if grant.status != ConsentStatus.PENDING:
        raise ConflictError("This invitation is no longer pending.")
    expiry = _aware(grant.expires_at)
    if expiry is not None and expiry <= _now():
        grant.status = ConsentStatus.EXPIRED
        db.flush()
        raise ConflictError("This invitation has expired.")

    grant.status = ConsentStatus.ACTIVE
    grant.accepted_at = _now()
    db.flush()
    record_audit(
        db,
        action="consent.accepted",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=grant.patient_id,
        resource_type="consent_grant",
        resource_id=str(grant.id),
        request=request,
    )
    return grant


@router.post(
    "/consents/{consent_id}/decline",
    response_model=ConsentOut,
    summary="Decline a consent invitation (grantee only)",
)
def decline_consent(
    consent_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> ConsentGrant:
    grant = _load_grant(db, consent_id)
    if grant.grantee_user_id != user.id:
        raise NotFoundError(CONSENT_NOT_FOUND)
    if grant.status != ConsentStatus.PENDING:
        raise ConflictError("This invitation is no longer pending.")
    grant.status = ConsentStatus.DECLINED
    db.flush()
    record_audit(
        db,
        action="consent.declined",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=grant.patient_id,
        resource_type="consent_grant",
        resource_id=str(grant.id),
        request=request,
    )
    return grant


@router.post(
    "/consents/{consent_id}/revoke",
    response_model=ConsentOut,
    summary="Revoke a consent grant (patient, guardian or the grantee)",
)
def revoke_consent(
    consent_id: uuid.UUID,
    payload: ConsentRevokeRequest,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> ConsentGrant:
    grant = _load_grant(db, consent_id)
    if grant.grantee_user_id != user.id:
        patient = db.get(PatientProfile, grant.patient_id)
        if patient is None:
            raise NotFoundError(CONSENT_NOT_FOUND)
        require_consent_manager(db, user=user, patient=patient, request=request)

    if grant.status == ConsentStatus.REVOKED:
        raise ConflictError("This consent grant is already revoked.")

    grant.status = ConsentStatus.REVOKED
    grant.revoked_at = _now()
    grant.revoked_by_user_id = user.id
    grant.revoked_reason = payload.reason
    db.flush()
    record_audit(
        db,
        action="consent.revoked",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=grant.patient_id,
        resource_type="consent_grant",
        resource_id=str(grant.id),
        request=request,
        outcome=AuditOutcome.SUCCESS,
        context={"scopes": grant.scopes},
    )
    return grant
