"""Insurance extraction contract with the AI engine (v1, proposed).

The backend owns persistence, authorization, orchestration and audit. The AI
engine owns OCR, clause interpretation and extraction; nothing in this module
re-implements any of that.

Contract rules
--------------
* The version string must match ``BRIDGECARE_INSURANCE_CONTRACT_VERSION``.
* Unknown fields are rejected (``extra="forbid"``) so schema drift is loud.
* The AI engine may only submit coverage for human review: ``review_status`` is
  either absent or ``needs_review``. It can never assert patient confirmation or
  insurer verification.
* Every extracted fact must carry provenance (page or clause reference).
* A document must be attached to the policy and must have a ``clean`` IDTA scan
  verdict before its extraction is accepted.
* Submissions are idempotent on ``extraction_id``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.db.base import utcnow
from app.models.document import Document
from app.models.enums import (
    ActorType,
    CoverageFactSource,
    CoverageSource,
    CoverageVerificationStatus,
    ExtractionRequestStatus,
    FamilyRelationship,
    PolicyCoverageClass,
    PolicyType,
    PolicyVersionKind,
)
from app.models.insurance import (
    InsuranceExtractionRequest,
    InsuranceInsuredMember,
    InsurancePolicy,
    InsurancePolicyDocument,
)
from app.services.audit import record_audit
from app.services.idta import require_clean
from app.services.insurance import (
    active_facts,
    policyholder_can_include,
    record_version,
    upsert_fact,
    validate_value,
)

INSURANCE_CONTRACT_VERSION = "2026-11-insurance-contract-v1"


class InsuranceProvenanceIn(BaseModel):
    """Where a value came from. Snippets never travel: only their digest."""

    model_config = ConfigDict(extra="forbid")

    page: int | None = Field(default=None, ge=1)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    section: str | None = Field(default=None, max_length=120)
    clause_reference: str | None = Field(default=None, max_length=120)
    snippet_sha256: str | None = Field(default=None, min_length=8, max_length=64)
    model_version: str | None = Field(default=None, max_length=60)

    @model_validator(mode="after")
    def _has_a_locator(self) -> InsuranceProvenanceIn:
        if self.page is None and not self.clause_reference and not self.section:
            raise ValueError("provenance needs a page, section or clause_reference")
        return self


class CoverageFactIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_key: str = Field(min_length=2, max_length=60)
    value_text: str | None = Field(default=None, max_length=1500)
    value_numeric: Decimal | None = None
    value_percent: Decimal | None = None
    value_boolean: bool | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    provenance: InsuranceProvenanceIn


class PolicyFieldsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_number: str | None = Field(default=None, max_length=120)
    insurer_name: str | None = Field(default=None, max_length=200)
    policy_type: PolicyType | None = None
    coverage_class: PolicyCoverageClass | None = None
    holder_name: str | None = Field(default=None, max_length=200)
    valid_from: date | None = None
    valid_to: date | None = None
    sum_insured: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)

    @model_validator(mode="after")
    def _dates_consistent(self) -> PolicyFieldsIn:
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to must not precede valid_from")
        return self


class InsuredMemberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patient_id: uuid.UUID
    relationship: FamilyRelationship = FamilyRelationship.OTHER
    name_on_policy: str | None = Field(default=None, max_length=200)
    date_of_birth: date | None = None
    sum_insured_share: Decimal | None = Field(default=None, ge=0)
    is_primary: bool = False


class UncertaintyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_key: str | None = Field(default=None, max_length=60)
    reason: str = Field(min_length=3, max_length=300)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ClauseInterpretationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause_reference: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=3, max_length=1000)
    page: int | None = Field(default=None, ge=1)


class InsuranceExtractionEnvelope(BaseModel):
    """One policy document's worth of extracted insurance information."""

    model_config = ConfigDict(extra="forbid")

    contract_version: str = Field(min_length=1, max_length=40)
    extraction_id: str = Field(min_length=8, max_length=64)
    document_id: uuid.UUID
    patient_id: uuid.UUID
    policy_id: uuid.UUID
    engine_version: str = Field(min_length=1, max_length=40)
    received_at: datetime
    review_status: Literal["needs_review"] | None = None
    policy_fields: PolicyFieldsIn | None = None
    coverage_facts: list[CoverageFactIn] = Field(default_factory=list, max_length=100)
    insured_members: list[InsuredMemberIn] = Field(default_factory=list, max_length=20)
    uncertainties: list[UncertaintyIn] = Field(default_factory=list, max_length=50)
    clause_interpretations: list[ClauseInterpretationIn] = Field(default_factory=list, max_length=50)
    provenance: InsuranceProvenanceIn | None = None


def _apply_policy_fields(
    db: Session, *, policy: InsurancePolicy, fields: PolicyFieldsIn
) -> list[dict[str, Any]]:
    """Fill empty policy fields; report conflicts instead of overwriting."""
    conflicts: list[dict[str, Any]] = []
    values = fields.model_dump(exclude_unset=True, exclude_none=True)
    # ``coverage_class`` defaults to ``individual``, so a floater would always
    # look like a conflict. An extracted floater is an upgrade, not a clash.
    coverage_class = values.pop("coverage_class", None)
    for field, value in values.items():
        current = getattr(policy, field)
        if current in (None, "", 0):
            setattr(policy, field, value)
        elif str(current) != str(value):
            conflicts.append(
                {"field": field, "stored": str(current), "extracted": str(value)}
            )
    if coverage_class == PolicyCoverageClass.FAMILY_FLOATER:
        policy.coverage_class = PolicyCoverageClass.FAMILY_FLOATER
    # Extracted dates are merged field by field, so the range is checked against
    # the stored half too, not just within the envelope.
    if policy.valid_from and policy.valid_to and policy.valid_to < policy.valid_from:
        raise ValidationAppError(
            "Extracted validity ends before the stored validity begins."
        )
    db.flush()
    return conflicts


def _upsert_members(
    db: Session,
    *,
    policy: InsurancePolicy,
    members: list[InsuredMemberIn],
    actor_user_id: uuid.UUID | None,
) -> list[uuid.UUID]:
    touched: list[uuid.UUID] = []
    for member in members:
        if not policyholder_can_include(db, policy=policy, member_id=member.patient_id):
            raise ValidationAppError(
                "An insured member is not part of this policyholder's family."
            )
        existing = db.scalar(
            select(InsuranceInsuredMember).where(
                InsuranceInsuredMember.policy_id == policy.id,
                InsuranceInsuredMember.patient_id == member.patient_id,
            )
        )
        if existing is None:
            existing = InsuranceInsuredMember(
                policy_id=policy.id,
                patient_id=member.patient_id,
                added_by_user_id=actor_user_id,
            )
            db.add(existing)
        existing.relationship = member.relationship
        existing.name_on_policy = member.name_on_policy
        existing.date_of_birth = member.date_of_birth
        existing.sum_insured_share = member.sum_insured_share
        existing.is_primary = member.is_primary
        touched.append(member.patient_id)
    if members:
        policy.coverage_class = PolicyCoverageClass.FAMILY_FLOATER
    db.flush()
    return touched


def _completed_request(
    db: Session, *, policy: InsurancePolicy, document: Document, envelope: InsuranceExtractionEnvelope
) -> InsuranceExtractionRequest:
    request_row = db.scalar(
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
    if request_row is None:
        request_row = InsuranceExtractionRequest(
            policy_id=policy.id,
            document_id=document.id,
            contract_version=envelope.contract_version,
        )
        db.add(request_row)
    request_row.status = ExtractionRequestStatus.COMPLETED
    request_row.extraction_id = envelope.extraction_id
    request_row.engine_version = envelope.engine_version
    request_row.contract_version = envelope.contract_version
    request_row.completed_at = utcnow()
    request_row.attempts = (request_row.attempts or 0) + 1
    request_row.payload = envelope.model_dump(mode="json")
    db.flush()
    return request_row


def ingest_insurance_extraction(
    db: Session, *, envelope: InsuranceExtractionEnvelope, request: Request | None = None
) -> dict[str, Any]:
    settings = get_settings()
    if envelope.contract_version != settings.insurance_contract_version:
        raise ValidationAppError(
            "Unsupported insurance contract version '"
            f"{envelope.contract_version}'. The backend implements "
            f"'{settings.insurance_contract_version}'."
        )
    if envelope.review_status not in (None, "needs_review"):
        raise ValidationAppError(
            "The AI engine may only submit coverage for human review (needs_review)."
        )

    policy = db.get(InsurancePolicy, envelope.policy_id)
    if policy is None or policy.patient_id != envelope.patient_id:
        raise NotFoundError("Policy not found for this patient.")
    if policy.archived_at is not None:
        raise ConflictError("The policy has been archived.")

    document = db.get(Document, envelope.document_id)
    if document is None or document.patient_id != envelope.patient_id:
        raise NotFoundError("Document not found for this patient.")
    if document.archived_at is not None:
        raise ConflictError("The document has been archived.")
    require_clean(document)

    existing = db.scalar(
        select(InsuranceExtractionRequest).where(
            InsuranceExtractionRequest.extraction_id == envelope.extraction_id
        )
    )
    if existing is not None:
        if existing.policy_id != policy.id:
            raise ConflictError("extraction_id was already used for a different policy.")
        return {
            "extraction_id": existing.extraction_id,
            "status": str(existing.status),
            "created": False,
            "facts_written": 0,
            "members_recorded": 0,
            "policy_conflicts": 0,
            "uncertainties_recorded": 0,
        }

    attached = db.scalar(
        select(InsurancePolicyDocument).where(
            InsurancePolicyDocument.policy_id == policy.id,
            InsurancePolicyDocument.document_id == document.id,
        )
    )
    if attached is None:
        # Same invariant as the extract endpoint: a document is attached by the
        # patient, never silently by the AI engine.
        raise ConflictError("Attach the document to this policy before extracting it.")

    facts_written = 0
    for item in envelope.coverage_facts:
        values = validate_value(
            item.field_key,
            value_text=item.value_text,
            value_numeric=item.value_numeric,
            value_percent=item.value_percent,
            value_boolean=item.value_boolean,
        )
        upsert_fact(
            db,
            policy=policy,
            field_key=item.field_key,
            values=values,
            source=CoverageFactSource.EXTRACTED,
            verification_status=CoverageVerificationStatus.NEEDS_REVIEW,
            provenance=item.provenance.model_dump(mode="json", exclude_none=True),
            confidence=item.confidence,
            source_document_id=document.id,
        )
        facts_written += 1

    policy_conflicts = (
        _apply_policy_fields(db, policy=policy, fields=envelope.policy_fields)
        if envelope.policy_fields is not None
        else []
    )
    members_recorded = _upsert_members(
        db, policy=policy, members=envelope.insured_members, actor_user_id=None
    )

    if envelope.uncertainties:
        for uncertainty in envelope.uncertainties:
            if uncertainty.field_key:
                fact = next(
                    (
                        item
                        for item in active_facts(db, policy.id)
                        if item.field_key == uncertainty.field_key
                    ),
                    None,
                )
                if fact is not None:
                    fact.provenance = {
                        **(fact.provenance or {}),
                        "uncertainty": uncertainty.reason[:300],
                    }
        db.flush()

    if policy.coverage_source != CoverageSource.INSURER_VERIFIED:
        policy.coverage_source = CoverageSource.DOCUMENT
    record_version(
        db,
        policy=policy,
        kind=PolicyVersionKind.EXTRACTION,
        actor_user_id=None,
        change_summary=(
            f"Extraction {envelope.extraction_id} added {facts_written} coverage values "
            "for review."
        ),
        source_document_id=document.id,
    )
    request_row = _completed_request(db, policy=policy, document=document, envelope=envelope)

    record_audit(
        db,
        action="insurance.extraction_ingested",
        actor_type=ActorType.AI_SERVICE,
        patient_id=policy.patient_id,
        resource_type="insurance_policy",
        resource_id=str(policy.id),
        request=request,
        context={
            "extraction_id": envelope.extraction_id,
            "contract_version": envelope.contract_version,
            "engine_version": envelope.engine_version,
            "facts_written": facts_written,
            "members_recorded": len(members_recorded),
            "policy_conflicts": len(policy_conflicts),
            "uncertainties": len(envelope.uncertainties),
            "clause_interpretations": len(envelope.clause_interpretations),
        },
    )

    return {
        "extraction_id": request_row.extraction_id,
        "status": str(request_row.status),
        "created": True,
        "facts_written": facts_written,
        "members_recorded": len(members_recorded),
        "policy_conflicts": len(policy_conflicts),
        "uncertainties_recorded": len(envelope.uncertainties),
        "verification_status": CoverageVerificationStatus.NEEDS_REVIEW.value,
    }

