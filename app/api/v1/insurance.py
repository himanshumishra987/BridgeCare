"""Insurance and healthcare information endpoints.

All claim statuses exposed here are user-reported unless
``status_is_insurer_verified`` is true, and policy coverage is only described as
confirmed when an insurer verification reference exists.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_roles
from app.core.config import get_settings
from app.db.base import utcnow
from app.core.errors import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationAppError,
)
from app.models.document import Document
from app.models.enums import (
    AccessScope,
    CoverageFactSource,
    CoverageSource,
    CoverageVerificationStatus,
    ExtractionRequestStatus,
    PolicyCoverageClass,
    PolicyDocumentRole,
    PolicyStatus,
    PolicyVersionKind,
    UserRole,
)
from app.models.insurance import (
    AyushmanCard,
    Claim,
    ClaimDocument,
    Hospitalisation,
    InsuranceCoverageFact,
    InsuranceExtractionRequest,
    InsuranceInsuredMember,
    InsurancePolicy,
    InsurancePolicyDocument,
    InsurancePolicyVersion,
    Insurer,
)
from app.schemas.insurance import (
    AyushmanCardCreate,
    AyushmanCardOut,
    ClaimCreate,
    ClaimDocumentCreate,
    ClaimDocumentOut,
    ClaimOut,
    ClaimUpdate,
    CoverageConfirmOut,
    CoverageConfirmRequest,
    CoverageFactOut,
    CoverageFactWrite,
    CoverageOut,
    ExtractionReceiptOut,
    ExtractionRequestOut,
    ExtractionTriggerRequest,
    HospitalisationCreate,
    HospitalisationOut,
    InsuredMemberCreate,
    InsuredMemberOut,
    InsurerCreate,
    InsurerOut,
    InsurerVerifyOut,
    InsurerVerifyRequest,
    PolicyCreate,
    PolicyDetailOut,
    PolicyDocumentAttach,
    PolicyDocumentOut,
    PolicyGuidanceOut,
    PolicyOut,
    PolicyUpdate,
    PolicyVersionOut,
)
from app.services import insurance as insurance_service
from app.services import insurer_verification
from app.services.access import require_patient_access, require_patient_write_access
from app.services.audit import record_audit
from app.services.idta import require_clean

router = APIRouter(tags=["Insurance"])

POLICY_NOT_FOUND = "Policy not found or not accessible."
CARD_NOT_FOUND = "Ayushman card not found or not accessible."
CLAIM_NOT_FOUND = "Claim not found or not accessible."
HOSPITALISATION_NOT_FOUND = "Hospitalisation not found or not accessible."


# --------------------------------------------------------------------------- catalogue
@router.get("/insurers", response_model=list[InsurerOut], summary="List known insurers")
def list_insurers(user: CurrentUser, db: DbSession) -> list[InsurerOut]:
    del user
    rows = db.scalars(select(Insurer).order_by(Insurer.name.asc()))
    return [InsurerOut.model_validate(row) for row in rows]


@router.post(
    "/insurers",
    response_model=InsurerOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add an insurer to the catalogue (administrator only)",
    dependencies=[Depends(require_roles(UserRole.ADMIN))],
)
def add_insurer(payload: InsurerCreate, db: DbSession) -> Insurer:
    if db.scalar(select(Insurer.id).where(Insurer.name == payload.name.strip())) is not None:
        raise ConflictError("That insurer already exists.")
    insurer = Insurer(
        name=payload.name.strip(),
        short_name=payload.short_name,
        regulator_reference=payload.regulator_reference,
        country_code=payload.country_code.upper(),
    )
    db.add(insurer)
    db.flush()
    return insurer


# --------------------------------------------------------------------------- policies
@router.post(
    "/patients/{patient_id}/insurance/policies",
    response_model=PolicyOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a policy (coverage is not confirmed until insurer-verified)",
)
def add_policy(
    patient_id: uuid.UUID,
    payload: PolicyCreate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> InsurancePolicy:
    require_patient_write_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.INSURANCE,
        request=request,
        action="insurance.policy.create",
    )
    if payload.insurer_id is not None and db.get(Insurer, payload.insurer_id) is None:
        raise ValidationAppError("Unknown insurer.")
    policy = InsurancePolicy(
        patient_id=patient_id,
        insurer_id=payload.insurer_id,
        insurer_name_text=payload.insurer_name_text,
        policy_number=payload.policy_number,
        policy_type=payload.policy_type,
        holder_name=payload.holder_name,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        sum_insured=payload.sum_insured,
        currency=payload.currency.upper(),
        coverage_details=payload.coverage_details,
        coverage_source=payload.coverage_source,
        coverage_class=payload.coverage_class,
        policyholder_patient_id=patient_id,
        status=payload.status,
        created_by_user_id=user.id,
    )
    db.add(policy)
    db.flush()

    # Insured members are explicit associations. A family floater is one policy
    # with several members, never duplicated individual policies.
    member_ids = list(dict.fromkeys(payload.insured_member_profile_ids))
    if patient_id not in member_ids:
        member_ids.insert(0, patient_id)
    for index, member_id in enumerate(member_ids):
        if not insurance_service.policyholder_can_include(
            db, policy=policy, member_id=member_id
        ):
            raise ValidationAppError(
                "An insured member is not part of this policyholder's family."
            )
        db.add(
            InsuranceInsuredMember(
                policy_id=policy.id,
                patient_id=member_id,
                is_primary=index == 0,
                added_by_user_id=user.id,
            )
        )
    if len(member_ids) > 1:
        policy.coverage_class = PolicyCoverageClass.FAMILY_FLOATER
    db.flush()
    insurance_service.record_version(
        db,
        policy=policy,
        kind=PolicyVersionKind.CREATED,
        actor_user_id=user.id,
        change_summary="Policy created.",
    )
    record_audit(
        db,
        action="insurance.policy_created",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=patient_id,
        resource_type="insurance_policy",
        resource_id=str(policy.id),
        request=request,
        context={"coverage_source": str(policy.coverage_source)},
    )
    return policy


@router.get(
    "/patients/{patient_id}/insurance/policies",
    response_model=list[PolicyOut],
    summary="List policies",
)
def list_policies(
    patient_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    include_archived: bool = Query(default=False),
) -> list[PolicyOut]:
    require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.INSURANCE,
        request=request,
        action="insurance.policy.list",
    )
    statement = select(InsurancePolicy).where(InsurancePolicy.patient_id == patient_id)
    if not include_archived:
        statement = statement.where(InsurancePolicy.archived_at.is_(None))
    rows = db.scalars(statement.order_by(InsurancePolicy.created_at.desc()))
    return [PolicyOut.model_validate(row) for row in rows]


def _load_policy(db: DbSession, policy_id: uuid.UUID) -> InsurancePolicy:
    policy = db.get(InsurancePolicy, policy_id)
    if policy is None:
        raise NotFoundError(POLICY_NOT_FOUND)
    return policy


@router.patch(
    "/insurance/policies/{policy_id}",
    response_model=PolicyOut,
    summary="Update a policy",
)
def update_policy(
    policy_id: uuid.UUID,
    payload: PolicyUpdate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> InsurancePolicy:
    policy = _load_policy(db, policy_id)
    require_patient_write_access(
        db,
        user=user,
        patient_id=policy.patient_id,
        scope=AccessScope.INSURANCE,
        request=request,
        action="insurance.policy.update",
    )
    if policy.archived_at is not None:
        raise ConflictError("This policy is archived. Restore it before editing.")
    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(policy, field, value)
    if policy.valid_from and policy.valid_to and policy.valid_to < policy.valid_from:
        raise ValidationAppError("valid_to must not precede valid_from.")
    # ``coverage_source`` is not writable here: only the insurer verification
    # integration can move it to INSURER_VERIFIED. Any edit drops a stale
    # verification timestamp; ``verification_reference`` was applied above.
    if policy.coverage_source != CoverageSource.INSURER_VERIFIED:
        policy.coverage_verified_at = None
    db.flush()
    insurance_service.record_version(
        db,
        policy=policy,
        kind=PolicyVersionKind.MANUAL_UPDATE,
        actor_user_id=user.id,
        change_summary=f"Policy updated: {', '.join(sorted(updates)) or 'no changes'}.",
    )
    record_audit(
        db,
        action="insurance.policy_updated",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=policy.patient_id,
        resource_type="insurance_policy",
        resource_id=str(policy.id),
        request=request,
        context={"fields": sorted(updates)},
    )
    return policy


# --------------------------------------------------------------------------- ayushman
@router.post(
    "/patients/{patient_id}/insurance/ayushman-cards",
    response_model=AyushmanCardOut,
    status_code=status.HTTP_201_CREATED,
    summary="Store Ayushman Bharat card details",
)
def add_ayushman_card(
    patient_id: uuid.UUID,
    payload: AyushmanCardCreate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> AyushmanCard:
    require_patient_write_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.INSURANCE,
        request=request,
        action="insurance.ayushman.create",
    )
    card = AyushmanCard(
        patient_id=patient_id,
        scheme=payload.scheme,
        card_number=payload.card_number.strip(),
        beneficiary_name=payload.beneficiary_name,
        family_id=payload.family_id,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        created_by_user_id=user.id,
    )
    db.add(card)
    db.flush()
    record_audit(
        db,
        action="insurance.ayushman_card_added",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=patient_id,
        resource_type="ayushman_card",
        resource_id=str(card.id),
        request=request,
    )
    return card


@router.get(
    "/patients/{patient_id}/insurance/ayushman-cards",
    response_model=list[AyushmanCardOut],
    summary="List Ayushman cards (numbers masked)",
)
def list_ayushman_cards(
    patient_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> list[AyushmanCardOut]:
    require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.INSURANCE,
        request=request,
        action="insurance.ayushman.list",
    )
    rows = db.scalars(
        select(AyushmanCard)
        .where(AyushmanCard.patient_id == patient_id)
        .order_by(AyushmanCard.created_at.desc())
    )
    return [AyushmanCardOut.model_validate(row) for row in rows]


# --------------------------------------------------------------------------- hospitalisation
@router.post(
    "/patients/{patient_id}/insurance/hospitalisations",
    response_model=HospitalisationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a hospitalisation and its expenses",
)
def add_hospitalisation(
    patient_id: uuid.UUID,
    payload: HospitalisationCreate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> Hospitalisation:
    require_patient_write_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.INSURANCE,
        request=request,
        action="insurance.hospitalisation.create",
    )
    hospitalisation = Hospitalisation(
        patient_id=patient_id,
        facility_name=payload.facility_name,
        admission_date=payload.admission_date,
        discharge_date=payload.discharge_date,
        reason_summary=payload.reason_summary,
        total_amount=payload.total_amount,
        currency=payload.currency.upper(),
        created_by_user_id=user.id,
    )
    db.add(hospitalisation)
    db.flush()
    record_audit(
        db,
        action="insurance.hospitalisation_added",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=patient_id,
        resource_type="hospitalisation",
        resource_id=str(hospitalisation.id),
        request=request,
    )
    return hospitalisation


@router.get(
    "/patients/{patient_id}/insurance/hospitalisations",
    response_model=list[HospitalisationOut],
    summary="List hospitalisations",
)
def list_hospitalisations(
    patient_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> list[HospitalisationOut]:
    require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.INSURANCE,
        request=request,
        action="insurance.hospitalisation.list",
    )
    rows = db.scalars(
        select(Hospitalisation)
        .where(Hospitalisation.patient_id == patient_id)
        .order_by(Hospitalisation.admission_date.desc())
    )
    return [HospitalisationOut.model_validate(row) for row in rows]


# --------------------------------------------------------------------------- claims
@router.post(
    "/patients/{patient_id}/insurance/claims",
    response_model=ClaimOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a claim with a user-reported status",
)
def add_claim(
    patient_id: uuid.UUID,
    payload: ClaimCreate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> Claim:
    require_patient_write_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.INSURANCE,
        request=request,
        action="insurance.claim.create",
    )
    if payload.policy_id is not None:
        policy = db.get(InsurancePolicy, payload.policy_id)
        if policy is None or policy.patient_id != patient_id:
            raise ValidationAppError("Policy does not belong to this patient.")
    if payload.hospitalisation_id is not None:
        hospitalisation = db.get(Hospitalisation, payload.hospitalisation_id)
        if hospitalisation is None or hospitalisation.patient_id != patient_id:
            raise ValidationAppError("Hospitalisation does not belong to this patient.")

    claim = Claim(
        patient_id=patient_id,
        policy_id=payload.policy_id,
        hospitalisation_id=payload.hospitalisation_id,
        claim_number=payload.claim_number,
        submitted_on=payload.submitted_on,
        user_reported_status=payload.user_reported_status,
        user_status_updated_at=utcnow(),
        notes=payload.notes,
        created_by_user_id=user.id,
    )
    db.add(claim)
    db.flush()
    record_audit(
        db,
        action="insurance.claim_created",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=patient_id,
        resource_type="claim",
        resource_id=str(claim.id),
        request=request,
    )
    return claim


@router.get(
    "/patients/{patient_id}/insurance/claims",
    response_model=list[ClaimOut],
    summary="List claims with explicit verification state",
)
def list_claims(
    patient_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> list[ClaimOut]:
    require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.INSURANCE,
        request=request,
        action="insurance.claim.list",
    )
    rows = db.scalars(
        select(Claim)
        .where(Claim.patient_id == patient_id)
        .order_by(Claim.created_at.desc())
    )
    return [ClaimOut.model_validate(row) for row in rows]


def _load_claim(db: DbSession, claim_id: uuid.UUID) -> Claim:
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise NotFoundError(CLAIM_NOT_FOUND)
    return claim


@router.patch(
    "/claims/{claim_id}",
    response_model=ClaimOut,
    summary="Update my user-reported claim status",
)
def update_claim(
    claim_id: uuid.UUID,
    payload: ClaimUpdate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> Claim:
    claim = _load_claim(db, claim_id)
    require_patient_write_access(
        db,
        user=user,
        patient_id=claim.patient_id,
        scope=AccessScope.INSURANCE,
        request=request,
        action="insurance.claim.update",
    )
    updates = payload.model_dump(exclude_unset=True)
    status_changed = (
        "user_reported_status" in updates
        and updates["user_reported_status"] != claim.user_reported_status
    )
    for field, value in updates.items():
        setattr(claim, field, value)
    if status_changed:
        claim.user_status_updated_at = utcnow()
    db.flush()
    record_audit(
        db,
        action="insurance.claim_updated",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=claim.patient_id,
        resource_type="claim",
        resource_id=str(claim.id),
        request=request,
        context={"fields": sorted(updates)},
    )
    return claim


@router.post(
    "/claims/{claim_id}/documents",
    response_model=ClaimDocumentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Attach an existing document to a claim",
)
def attach_claim_document(
    claim_id: uuid.UUID,
    payload: ClaimDocumentCreate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> ClaimDocument:
    claim = _load_claim(db, claim_id)
    require_patient_write_access(
        db,
        user=user,
        patient_id=claim.patient_id,
        scope=AccessScope.INSURANCE,
        request=request,
        action="insurance.claim.document.attach",
    )
    document = db.get(Document, payload.document_id)
    if document is None or document.patient_id != claim.patient_id:
        raise ValidationAppError("Document does not belong to this patient.")
    existing = db.scalar(
        select(ClaimDocument).where(
            ClaimDocument.claim_id == claim.id,
            ClaimDocument.document_id == document.id,
        )
    )
    if existing is not None:
        raise ConflictError("That document is already attached to this claim.")
    link = ClaimDocument(claim_id=claim.id, document_id=document.id, kind=payload.kind)
    db.add(link)
    db.flush()
    record_audit(
        db,
        action="insurance.claim_document_attached",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=claim.patient_id,
        resource_type="claim_document",
        resource_id=str(link.id),
        request=request,
    )
    return link


@router.get(
    "/claims/{claim_id}/documents",
    response_model=list[ClaimDocumentOut],
    summary="List documents attached to a claim",
)
def list_claim_documents(
    claim_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> list[ClaimDocumentOut]:
    claim = _load_claim(db, claim_id)
    require_patient_access(
        db,
        user=user,
        patient_id=claim.patient_id,
        scope=AccessScope.INSURANCE,
        request=request,
        action="insurance.claim.document.list",
    )
    rows = db.scalars(
        select(ClaimDocument)
        .where(ClaimDocument.claim_id == claim.id)
        .order_by(ClaimDocument.created_at.asc())
    )
    return [ClaimDocumentOut.model_validate(row) for row in rows]


# --------------------------------------------------------------------------- policy detail
def _authorize_policy_read(
    db: DbSession, *, policy: InsurancePolicy, user: CurrentUser, request: Request, action: str
) -> None:
    require_patient_access(
        db,
        user=user,
        patient_id=policy.patient_id,
        scope=AccessScope.INSURANCE,
        request=request,
        action=action,
    )


def _authorize_policy_write(
    db: DbSession, *, policy: InsurancePolicy, user: CurrentUser, request: Request, action: str
) -> None:
    require_patient_write_access(
        db,
        user=user,
        patient_id=policy.patient_id,
        scope=AccessScope.INSURANCE,
        request=request,
        action=action,
    )
    if policy.archived_at is not None:
        raise ConflictError("This policy is archived. Restore it before changing it.")


def _policy_documents(
    db: DbSession, policy_id: uuid.UUID
) -> list[tuple[InsurancePolicyDocument, Document]]:
    rows = db.execute(
        select(InsurancePolicyDocument, Document)
        .join(Document, Document.id == InsurancePolicyDocument.document_id)
        .where(InsurancePolicyDocument.policy_id == policy_id)
        .order_by(InsurancePolicyDocument.created_at.asc())
    ).all()
    return [(link, document) for link, document in rows]


def _document_link_out(link: InsurancePolicyDocument, document: Document) -> PolicyDocumentOut:
    return PolicyDocumentOut(
        id=link.id,
        policy_id=link.policy_id,
        document_id=link.document_id,
        role=link.role,
        endorsement_reference=link.endorsement_reference,
        added_by_user_id=link.added_by_user_id,
        created_at=link.created_at,
        document_scan_status=str(document.scan_status),
        content_type=document.content_type,
        byte_size=document.byte_size,
    )


def _policy_versions(db: DbSession, policy_id: uuid.UUID) -> list[InsurancePolicyVersion]:
    return list(
        db.scalars(
            select(InsurancePolicyVersion)
            .where(InsurancePolicyVersion.policy_id == policy_id)
            .order_by(InsurancePolicyVersion.version_number.desc())
        )
    )


def _insured_members(db: DbSession, policy_id: uuid.UUID) -> list[InsuranceInsuredMember]:
    return list(
        db.scalars(
            select(InsuranceInsuredMember)
            .where(InsuranceInsuredMember.policy_id == policy_id)
            .order_by(InsuranceInsuredMember.is_primary.desc(), InsuranceInsuredMember.created_at.asc())
        )
    )


def _coverage_payload(
    policy: InsurancePolicy, facts: list[InsuranceCoverageFact]
) -> CoverageOut:
    summary = insurance_service.coverage_summary(policy, facts)
    return CoverageOut(
        **summary,
        facts=[CoverageFactOut.model_validate(fact) for fact in facts],
    )


@router.get(
    "/insurance/policies/{policy_id}",
    response_model=PolicyDetailOut,
    summary="Read one policy with its insured members, documents, coverage and history",
)
def read_policy(
    policy_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> PolicyDetailOut:
    policy = _load_policy(db, policy_id)
    _authorize_policy_read(
        db, policy=policy, user=user, request=request, action="insurance.policy.view"
    )
    document_rows = _policy_documents(db, policy.id)
    return PolicyDetailOut(
        policy=PolicyOut.model_validate(policy),
        insured_members=[InsuredMemberOut.model_validate(row) for row in _insured_members(db, policy.id)],
        documents=[_document_link_out(link, document) for link, document in document_rows],
        coverage=_coverage_payload(policy, insurance_service.active_facts(db, policy.id)),
        versions=[
            PolicyVersionOut.model_validate(version)
            for version in _policy_versions(db, policy.id)
        ],
    )


@router.post(
    "/insurance/policies/{policy_id}/archive",
    response_model=PolicyOut,
    summary="Archive (deactivate) a policy without deleting its history",
)
def archive_policy(
    policy_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> InsurancePolicy:
    policy = _load_policy(db, policy_id)
    _authorize_policy_write(
        db, policy=policy, user=user, request=request, action="insurance.policy.archive"
    )
    if policy.archived_at is not None:
        raise ConflictError("This policy is already archived.")
    policy.archived_at = utcnow()
    policy.status = PolicyStatus.LAPSED
    db.flush()
    insurance_service.record_version(
        db,
        policy=policy,
        kind=PolicyVersionKind.MANUAL_UPDATE,
        actor_user_id=user.id,
        change_summary="Policy archived.",
    )
    record_audit(
        db,
        action="insurance.policy_archived",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=policy.patient_id,
        resource_type="insurance_policy",
        resource_id=str(policy.id),
        request=request,
    )
    return policy


# --------------------------------------------------------------------------- policy documents
@router.post(
    "/insurance/policies/{policy_id}/documents",
    response_model=PolicyDocumentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Attach an uploaded document to a policy",
)
def attach_policy_document(
    policy_id: uuid.UUID,
    payload: PolicyDocumentAttach,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> PolicyDocumentOut:
    policy = _load_policy(db, policy_id)
    _authorize_policy_write(
        db, policy=policy, user=user, request=request, action="insurance.policy.document.attach"
    )
    document = db.get(Document, payload.document_id)
    if document is None or document.patient_id != policy.patient_id:
        raise ValidationAppError("Document does not belong to this patient.")
    if document.archived_at is not None:
        raise ConflictError("That document is archived.")
    existing = db.scalar(
        select(InsurancePolicyDocument).where(
            InsurancePolicyDocument.policy_id == policy.id,
            InsurancePolicyDocument.document_id == document.id,
        )
    )
    if existing is not None:
        raise ConflictError("That document is already attached to this policy.")

    link = InsurancePolicyDocument(
        policy_id=policy.id,
        document_id=document.id,
        role=payload.role,
        endorsement_reference=payload.endorsement_reference,
        added_by_user_id=user.id,
    )
    db.add(link)
    db.flush()
    if payload.role == PolicyDocumentRole.ENDORSEMENT:
        insurance_service.record_version(
            db,
            policy=policy,
            kind=PolicyVersionKind.ENDORSEMENT,
            actor_user_id=user.id,
            change_summary="Endorsement document attached.",
            source_document_id=document.id,
            endorsement_reference=payload.endorsement_reference,
        )
    record_audit(
        db,
        action="insurance.policy_document_attached",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=policy.patient_id,
        resource_type="insurance_policy_document",
        resource_id=str(link.id),
        request=request,
        context={"role": str(payload.role), "scan_status": str(document.scan_status)},
    )
    return _document_link_out(link, document)


@router.get(
    "/insurance/policies/{policy_id}/documents",
    response_model=list[PolicyDocumentOut],
    summary="List documents attached to a policy",
)
def list_policy_documents(
    policy_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> list[PolicyDocumentOut]:
    policy = _load_policy(db, policy_id)
    _authorize_policy_read(
        db, policy=policy, user=user, request=request, action="insurance.policy.document.list"
    )
    return [
        _document_link_out(link, document)
        for link, document in _policy_documents(db, policy.id)
    ]


# --------------------------------------------------------------------------- extraction orchestration
@router.post(
    "/insurance/policies/{policy_id}/extract",
    response_model=ExtractionRequestOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue an attached, clean-scanned document for AI insurance extraction",
)
def request_insurance_extraction(
    policy_id: uuid.UUID,
    payload: ExtractionTriggerRequest,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> InsuranceExtractionRequest:
    policy = _load_policy(db, policy_id)
    _authorize_policy_write(
        db, policy=policy, user=user, request=request, action="insurance.policy.extract"
    )
    settings = get_settings()
    if not settings.ai_service_key:
        raise ServiceUnavailableError(
            "The AI engine integration is not configured on this deployment."
        )
    document = db.get(Document, payload.document_id)
    if document is None or document.patient_id != policy.patient_id:
        raise ValidationAppError("Document does not belong to this patient.")
    attached = db.scalar(
        select(InsurancePolicyDocument).where(
            InsurancePolicyDocument.policy_id == policy.id,
            InsurancePolicyDocument.document_id == document.id,
        )
    )
    if attached is None:
        raise ConflictError("Attach the document to this policy before extracting it.")
    # IDTA gate: nothing is queued for an unscanned, errored or infected document.
    require_clean(document)

    existing = db.scalar(
        select(InsuranceExtractionRequest)
        .where(
            InsuranceExtractionRequest.policy_id == policy.id,
            InsuranceExtractionRequest.document_id == document.id,
            InsuranceExtractionRequest.status.in_(
                [ExtractionRequestStatus.QUEUED, ExtractionRequestStatus.PROCESSING]
            ),
        )
        .order_by(InsuranceExtractionRequest.created_at.desc())
        .limit(1)
    )
    if existing is not None:
        return existing

    row = InsuranceExtractionRequest(
        policy_id=policy.id,
        document_id=document.id,
        requested_by_user_id=user.id,
        contract_version=settings.insurance_contract_version,
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        action="insurance.extraction_requested",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=policy.patient_id,
        resource_type="insurance_policy",
        resource_id=str(policy.id),
        request=request,
        context={"document_id": str(document.id)},
    )
    return row


@router.get(
    "/insurance/policies/{policy_id}/extractions",
    response_model=list[ExtractionReceiptOut],
    summary="Read AI extraction receipts (interpretations and uncertainties only)",
)
def list_extraction_receipts(
    policy_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> list[ExtractionReceiptOut]:
    policy = _load_policy(db, policy_id)
    _authorize_policy_read(
        db, policy=policy, user=user, request=request, action="insurance.extraction.list"
    )
    rows = db.scalars(
        select(InsuranceExtractionRequest)
        .where(InsuranceExtractionRequest.policy_id == policy.id)
        .order_by(InsuranceExtractionRequest.created_at.desc())
    )
    receipts: list[ExtractionReceiptOut] = []
    for row in rows:
        payload: dict[str, Any] = row.payload or {}
        receipts.append(
            ExtractionReceiptOut(
                extraction_id=row.extraction_id,
                status=row.status,
                engine_version=row.engine_version,
                completed_at=row.completed_at,
                uncertainties=payload.get("uncertainties") or [],
                clause_interpretations=payload.get("clause_interpretations") or [],
            )
        )
    return receipts


# --------------------------------------------------------------------------- coverage
@router.get(
    "/insurance/policies/{policy_id}/coverage",
    response_model=CoverageOut,
    summary="Coverage values with their provenance and verification state",
)
def read_coverage(
    policy_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> CoverageOut:
    policy = _load_policy(db, policy_id)
    _authorize_policy_read(
        db, policy=policy, user=user, request=request, action="insurance.coverage.view"
    )
    return _coverage_payload(policy, insurance_service.active_facts(db, policy.id))


@router.post(
    "/insurance/policies/{policy_id}/coverage",
    response_model=CoverageFactOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a coverage value by hand (never insurer-verified)",
)
def add_coverage_fact(
    policy_id: uuid.UUID,
    payload: CoverageFactWrite,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> InsuranceCoverageFact:
    policy = _load_policy(db, policy_id)
    _authorize_policy_write(
        db, policy=policy, user=user, request=request, action="insurance.coverage.add"
    )
    values = insurance_service.validate_value(
        payload.field_key,
        value_text=payload.value_text,
        value_numeric=payload.value_numeric,
        value_percent=payload.value_percent,
        value_boolean=payload.value_boolean,
    )
    fact = insurance_service.upsert_fact(
        db,
        policy=policy,
        field_key=payload.field_key,
        values=values,
        source=CoverageFactSource.MANUAL,
        verification_status=CoverageVerificationStatus.MANUALLY_ENTERED,
        provenance={"entered_by_user_id": str(user.id), "note": payload.note},
    )
    insurance_service.record_version(
        db,
        policy=policy,
        kind=PolicyVersionKind.MANUAL_UPDATE,
        actor_user_id=user.id,
        change_summary=f"Coverage value recorded: {payload.field_key}.",
    )
    record_audit(
        db,
        action="insurance.coverage_added",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=policy.patient_id,
        resource_type="insurance_coverage_fact",
        resource_id=str(fact.id),
        request=request,
        context={"field_key": payload.field_key},
    )
    return fact


@router.patch(
    "/insurance/policies/{policy_id}/coverage/{field_key}",
    response_model=CoverageFactOut,
    summary="Correct a coverage value, keeping the extracted original",
)
def correct_coverage_fact(
    policy_id: uuid.UUID,
    field_key: str,
    payload: CoverageFactWrite,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> InsuranceCoverageFact:
    policy = _load_policy(db, policy_id)
    _authorize_policy_write(
        db, policy=policy, user=user, request=request, action="insurance.coverage.correct"
    )
    if payload.field_key != field_key:
        raise ValidationAppError("field_key in the body must match the path.")
    existing = insurance_service.fact_by_key(db, policy.id, field_key)
    if existing is None:
        raise NotFoundError("No coverage value is stored for that field.")
    values = insurance_service.validate_value(
        field_key,
        value_text=payload.value_text,
        value_numeric=payload.value_numeric,
        value_percent=payload.value_percent,
        value_boolean=payload.value_boolean,
    )
    fact = insurance_service.correct_fact(
        db,
        policy=policy,
        fact=existing,
        values=values,
        corrected_by_user_id=user.id,
        note=payload.note,
    )
    insurance_service.record_version(
        db,
        policy=policy,
        kind=PolicyVersionKind.MANUAL_UPDATE,
        actor_user_id=user.id,
        change_summary=f"Coverage value corrected: {field_key}.",
    )
    record_audit(
        db,
        action="insurance.coverage_corrected",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=policy.patient_id,
        resource_type="insurance_coverage_fact",
        resource_id=str(fact.id),
        request=request,
        context={"field_key": field_key},
    )
    return fact


@router.post(
    "/insurance/policies/{policy_id}/confirm",
    response_model=CoverageConfirmOut,
    summary="Patient confirmation of coverage values (not insurer verification)",
)
def confirm_coverage(
    policy_id: uuid.UUID,
    payload: CoverageConfirmRequest,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> CoverageConfirmOut:
    policy = _load_policy(db, policy_id)
    _authorize_policy_write(
        db, policy=policy, user=user, request=request, action="insurance.coverage.confirm"
    )
    facts = insurance_service.active_facts(db, policy.id)
    if not facts:
        raise ConflictError("This policy has no coverage values to confirm.")
    requested = list(dict.fromkeys(payload.field_keys or [fact.field_key for fact in facts]))
    by_key = {fact.field_key: fact for fact in facts}
    missing = [key for key in requested if key not in by_key]
    if missing:
        raise ValidationAppError("Unknown coverage fields: " + ", ".join(sorted(missing)))
    selected = [by_key[key] for key in requested]
    prior_states = sorted({str(fact.verification_status) for fact in selected})
    insurance_service.confirm_facts(
        db, policy=policy, facts=selected, confirmed_by_user_id=user.id
    )
    record_audit(
        db,
        action="insurance.coverage_confirmed",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=policy.patient_id,
        resource_type="insurance_policy",
        resource_id=str(policy.id),
        request=request,
        context={"fields": len(selected), "prior_states": prior_states, "note": payload.note},
    )
    return CoverageConfirmOut(
        policy_id=policy.id,
        confirmed_fields=[fact.field_key for fact in selected],
        coverage=_coverage_payload(policy, insurance_service.active_facts(db, policy.id)),
    )


@router.get(
    "/insurance/policies/{policy_id}/versions",
    response_model=list[PolicyVersionOut],
    summary="Policy version and endorsement history",
)
def list_policy_versions(
    policy_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> list[PolicyVersionOut]:
    policy = _load_policy(db, policy_id)
    _authorize_policy_read(
        db, policy=policy, user=user, request=request, action="insurance.policy.versions"
    )
    return [
        PolicyVersionOut.model_validate(row) for row in _policy_versions(db, policy.id)
    ]


@router.post(
    "/insurance/policies/{policy_id}/insured-members",
    response_model=InsuredMemberOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add an insured member to a family floater policy",
)
def add_insured_member(
    policy_id: uuid.UUID,
    payload: InsuredMemberCreate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> InsuranceInsuredMember:
    policy = _load_policy(db, policy_id)
    _authorize_policy_write(
        db, policy=policy, user=user, request=request, action="insurance.member.add"
    )
    if not insurance_service.policyholder_can_include(
        db, policy=policy, member_id=payload.patient_id
    ):
        raise ValidationAppError(
            "An insured member must be the policyholder or a profile they are guardian of."
        )
    existing = db.scalar(
        select(InsuranceInsuredMember).where(
            InsuranceInsuredMember.policy_id == policy.id,
            InsuranceInsuredMember.patient_id == payload.patient_id,
        )
    )
    if existing is not None:
        raise ConflictError("That person is already an insured member of this policy.")
    member = InsuranceInsuredMember(
        policy_id=policy.id,
        patient_id=payload.patient_id,
        relationship=payload.relationship,
        name_on_policy=payload.name_on_policy,
        date_of_birth=payload.date_of_birth,
        sum_insured_share=payload.sum_insured_share,
        is_primary=payload.is_primary,
        added_by_user_id=user.id,
    )
    db.add(member)
    policy.coverage_class = PolicyCoverageClass.FAMILY_FLOATER
    db.flush()
    insurance_service.record_version(
        db,
        policy=policy,
        kind=PolicyVersionKind.MANUAL_UPDATE,
        actor_user_id=user.id,
        change_summary="Insured member added.",
    )
    record_audit(
        db,
        action="insurance.member_added",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=policy.patient_id,
        resource_type="insurance_insured_member",
        resource_id=str(member.id),
        request=request,
        context={"relationship": str(payload.relationship)},
    )
    return member


@router.delete(
    "/insurance/insured-members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an insured member (the policyholder cannot be removed)",
)
def remove_insured_member(
    member_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> Response:
    member = db.get(InsuranceInsuredMember, member_id)
    if member is None:
        raise NotFoundError("Insured member not found or not accessible.")
    policy = _load_policy(db, member.policy_id)
    _authorize_policy_write(
        db, policy=policy, user=user, request=request, action="insurance.member.remove"
    )
    if member.patient_id == policy.policyholder_patient_id or member.is_primary:
        raise ConflictError("The policyholder cannot be removed from their own policy.")
    db.delete(member)
    db.flush()
    insurance_service.record_version(
        db,
        policy=policy,
        kind=PolicyVersionKind.MANUAL_UPDATE,
        actor_user_id=user.id,
        change_summary="Insured member removed.",
    )
    record_audit(
        db,
        action="insurance.member_removed",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=policy.patient_id,
        resource_type="insurance_insured_member",
        resource_id=str(member_id),
        request=request,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- guidance
@router.get(
    "/insurance/policies/{policy_id}/guidance",
    response_model=PolicyGuidanceOut,
    summary="Policy-grounded admission and claim guidance (guidance only)",
)
def policy_guidance(
    policy_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    admission_type: Literal["planned", "emergency"] = Query(default="planned"),
) -> PolicyGuidanceOut:
    policy = _load_policy(db, policy_id)
    _authorize_policy_read(
        db, policy=policy, user=user, request=request, action="insurance.guidance.view"
    )
    guidance = insurance_service.build_guidance_with_members(
        policy,
        insurance_service.active_facts(db, policy.id),
        _insured_members(db, policy.id),
        admission_type=admission_type,
    )
    record_audit(
        db,
        action="insurance.guidance_viewed",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=policy.patient_id,
        resource_type="insurance_policy",
        resource_id=str(policy.id),
        request=request,
        context={"admission_type": admission_type, "data_gaps": len(guidance["data_gaps"])},
    )
    return PolicyGuidanceOut(**guidance)


# --------------------------------------------------------------------------- insurer verification
@router.post(
    "/insurance/policies/{policy_id}/verify",
    response_model=InsurerVerifyOut,
    summary="Ask the insurer verification integration to confirm coverage",
)
def verify_insurance_policy(
    policy_id: uuid.UUID,
    payload: InsurerVerifyRequest,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> InsurerVerifyOut:
    policy = _load_policy(db, policy_id)
    _authorize_policy_write(
        db, policy=policy, user=user, request=request, action="insurance.policy.verify"
    )
    if not payload.patient_authorization_reference.strip():
        raise ValidationAppError(
            "A patient authorisation reference is required before insurer verification."
        )
    result = insurer_verification.verify_policy(
        db,
        policy=policy,
        authorization_reference=payload.patient_authorization_reference.strip(),
        actor_user_id=user.id,
        actor_role=str(user.role),
        request=request,
    )
    return InsurerVerifyOut(
        outcome=result.outcome,
        provider=result.provider,
        reference=result.reference,
        verified_fields=result.verified_fields,
        discrepancies=result.discrepancies,
        note=result.note,
        attempt_id=result.attempt_id,
        coverage_confirmed=policy.coverage_confirmed,
        policy=PolicyOut.model_validate(policy),
    )
