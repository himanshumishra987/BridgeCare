"""Authorization core.

Every patient-scoped endpoint funnels through this module. Rules:

* The account that owns a profile (``PatientProfile.user_id``) has full access.
* Any other user needs an ``ACTIVE``, unexpired ``ConsentGrant`` containing the
  required :class:`AccessScope`. Family relationship records are never consulted.
* ``ADMIN`` has **no** implicit access to health data: least privilege means an
  administrator can manage accounts, not read medical records.
* Unauthorized and non-existent patients return the same 404 so identifiers
  cannot be enumerated (IDOR defence).
* Denials are audited, which makes probing visible.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.models.consent import ConsentGrant
from app.models.enums import AccessScope, AuditOutcome, ConsentBasis, ConsentStatus, UserRole
from app.models.patient import PatientProfile
from app.models.user import User
from app.services.audit import record_audit

NOT_FOUND_MESSAGE = "Patient profile not found or not accessible."


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass(frozen=True)
class AccessContext:
    patient: PatientProfile
    user: User
    scopes: frozenset[AccessScope]
    is_owner: bool
    is_guardian: bool
    consent_id: uuid.UUID | None
    basis: str

    def has(self, scope: AccessScope) -> bool:
        return scope in self.scopes

    @property
    def can_write(self) -> bool:
        """Grants are read-only; only the record owner or a guardian may mutate."""
        return self.is_owner or self.is_guardian


def active_grants(
    db: Session, *, patient_id: uuid.UUID, grantee_user_id: uuid.UUID
) -> list[ConsentGrant]:
    """Return usable grants, lazily marking expired ones as EXPIRED."""
    grants = list(
        db.scalars(
            select(ConsentGrant).where(
                ConsentGrant.patient_id == patient_id,
                ConsentGrant.grantee_user_id == grantee_user_id,
            )
        )
    )
    now = _now()
    usable: list[ConsentGrant] = []
    for grant in grants:
        expires_at = _aware(grant.expires_at)
        if (
            grant.status == ConsentStatus.ACTIVE
            and expires_at is not None
            and expires_at <= now
        ):
            grant.status = ConsentStatus.EXPIRED
            usable_check = False
        else:
            usable_check = grant.status == ConsentStatus.ACTIVE and (
                expires_at is None or expires_at > now
            )
        if usable_check:
            usable.append(grant)
    if any(grant.status == ConsentStatus.EXPIRED for grant in grants):
        db.flush()
    return usable


def scopes_for(db: Session, *, user: User, patient: PatientProfile) -> tuple[set[AccessScope], uuid.UUID | None, bool]:
    """Return (scopes, primary_consent_id, is_guardian)."""
    if patient.user_id is not None and patient.user_id == user.id:
        return set(AccessScope), None, False

    granted: set[AccessScope] = set()
    guardian = False
    consent_id: uuid.UUID | None = None
    for grant in active_grants(db, patient_id=patient.id, grantee_user_id=user.id):
        valid_scopes = set()
        for raw in grant.scope_set():
            try:
                valid_scopes.add(AccessScope(raw))
            except ValueError:
                continue  # unknown/removed scope never grants anything
        granted |= valid_scopes
        if grant.basis == ConsentBasis.GUARDIANSHIP:
            guardian = True
        if consent_id is None:
            consent_id = grant.id
    return granted, consent_id, guardian


def get_patient_or_404(db: Session, patient_id: uuid.UUID) -> PatientProfile:
    patient = db.get(PatientProfile, patient_id)
    if patient is None:
        raise NotFoundError(NOT_FOUND_MESSAGE)
    return patient


def require_patient_access(
    db: Session,
    *,
    user: User,
    patient_id: uuid.UUID,
    scope: AccessScope,
    request: Request | None = None,
    action: str | None = None,
    resource_type: str | None = None,
) -> AccessContext:
    """Authorize read access to ``patient_id`` for ``scope``."""
    patient = db.get(PatientProfile, patient_id)
    if patient is None:
        raise NotFoundError(NOT_FOUND_MESSAGE)

    granted, consent_id, guardian = scopes_for(db, user=user, patient=patient)
    is_owner = patient.user_id is not None and patient.user_id == user.id
    if not is_owner and scope not in granted:
        record_audit(
            db,
            action=action or "access.denied",
            actor_user_id=user.id,
            actor_role=str(user.role),
            patient_id=patient_id,
            resource_type=resource_type or "patient_profile",
            resource_id=str(patient_id),
            outcome=AuditOutcome.DENIED,
            request=request,
            context={"required_scope": str(scope)},
        )
        raise NotFoundError(NOT_FOUND_MESSAGE)

    return AccessContext(
        patient=patient,
        user=user,
        scopes=frozenset(granted),
        is_owner=is_owner,
        is_guardian=guardian,
        consent_id=consent_id,
        basis="owner" if is_owner else ("guardianship" if guardian else "consent"),
    )


def require_patient_write_access(
    db: Session,
    *,
    user: User,
    patient_id: uuid.UUID,
    scope: AccessScope,
    request: Request | None = None,
    action: str | None = None,
) -> AccessContext:
    """Authorize mutation. Consent grants are read-only by design."""
    ctx = require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=scope,
        request=request,
        action=action,
    )
    if not ctx.can_write:
        record_audit(
            db,
            action="access.write_denied",
            actor_user_id=user.id,
            actor_role=str(user.role),
            patient_id=patient_id,
            resource_type="patient_profile",
            resource_id=str(patient_id),
            outcome=AuditOutcome.DENIED,
            request=request,
            context={"required_scope": str(scope)},
        )
        raise NotFoundError(NOT_FOUND_MESSAGE)
    return ctx


def require_record_verifier(
    db: Session,
    *,
    user: User,
    patient: PatientProfile,
    request: Request | None = None,
) -> AccessContext:
    """Authorize a human verification decision.

    Allowed for the record owner, an active guardian, or a clinician holding an
    active RECORDS grant. The AI service key is never sufficient.
    """
    granted, consent_id, guardian = scopes_for(db, user=user, patient=patient)
    is_owner = patient.user_id is not None and patient.user_id == user.id
    is_clinician = user.role == UserRole.CLINICIAN and AccessScope.RECORDS in granted
    if not (is_owner or guardian or is_clinician):
        record_audit(
            db,
            action="record.verify_denied",
            actor_user_id=user.id,
            actor_role=str(user.role),
            patient_id=patient.id,
            resource_type="health_record",
            outcome=AuditOutcome.DENIED,
            request=request,
        )
        raise NotFoundError(NOT_FOUND_MESSAGE)
    return AccessContext(
        patient=patient,
        user=user,
        scopes=frozenset(granted),
        is_owner=is_owner,
        is_guardian=guardian,
        consent_id=consent_id,
        basis="owner" if is_owner else ("guardianship" if guardian else "consent"),
    )


def require_consent_manager(
    db: Session,
    *,
    user: User,
    patient: PatientProfile,
    request: Request | None = None,
) -> AccessContext:
    """Only the record owner or an active guardian may grant or revoke consent."""
    ctx = require_patient_access(
        db,
        user=user,
        patient_id=patient.id,
        scope=AccessScope.FAMILY,
        request=request,
        action="consent.manage_denied",
    )
    if not ctx.can_write:
        record_audit(
            db,
            action="consent.manage_denied",
            actor_user_id=user.id,
            actor_role=str(user.role),
            patient_id=patient.id,
            resource_type="consent_grant",
            outcome=AuditOutcome.DENIED,
            request=request,
        )
        raise NotFoundError(NOT_FOUND_MESSAGE)
    return ctx
