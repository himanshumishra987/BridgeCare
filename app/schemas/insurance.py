from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, model_validator

from app.models.enums import (
    ClaimStatus,
    CoverageFactSource,
    CoverageSource,
    CoverageVerificationStatus,
    ExtractionRequestStatus,
    FamilyRelationship,
    InsurerVerificationOutcome,
    PolicyCoverageClass,
    PolicyDocumentRole,
    PolicyStatus,
    PolicyType,
    PolicyVersionKind,
    VerificationStatus,
)
from app.schemas.common import ORMModel, StrictModel


class InsurerOut(ORMModel):
    id: uuid.UUID
    name: str
    short_name: str | None = None
    regulator_reference: str | None = None
    country_code: str


class InsurerCreate(StrictModel):
    name: str = Field(min_length=2, max_length=200)
    short_name: str | None = Field(default=None, max_length=80)
    regulator_reference: str | None = Field(default=None, max_length=120)
    country_code: str = Field(default="IN", min_length=2, max_length=2)


class PolicyCreate(StrictModel):
    insurer_id: uuid.UUID | None = None
    insurer_name_text: str | None = Field(default=None, max_length=200)
    policy_number: str = Field(min_length=2, max_length=120)
    policy_type: PolicyType = PolicyType.HEALTH
    coverage_class: PolicyCoverageClass = PolicyCoverageClass.INDIVIDUAL
    insured_member_profile_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    holder_name: str | None = Field(default=None, max_length=200)
    valid_from: date | None = None
    valid_to: date | None = None
    sum_insured: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    coverage_details: dict[str, Any] = Field(default_factory=dict)
    coverage_source: CoverageSource = CoverageSource.USER_ENTERED
    verification_reference: str | None = Field(default=None, max_length=200)
    status: PolicyStatus = PolicyStatus.UNKNOWN

    @model_validator(mode="after")
    def _no_self_asserted_verification(self) -> PolicyCreate:
        if self.coverage_source == CoverageSource.INSURER_VERIFIED:
            raise ValueError(
                "insurer_verified coverage can only be produced by the insurer "
                "verification integration; it cannot be asserted when creating a policy."
            )
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to must not precede valid_from.")
        return self


class PolicyUpdate(StrictModel):
    insurer_id: uuid.UUID | None = None
    insurer_name_text: str | None = Field(default=None, max_length=200)
    policy_number: str | None = Field(default=None, min_length=2, max_length=120)
    policy_type: PolicyType | None = None
    coverage_class: PolicyCoverageClass | None = None
    holder_name: str | None = Field(default=None, max_length=200)
    valid_from: date | None = None
    valid_to: date | None = None
    sum_insured: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    coverage_details: dict[str, Any] | None = None
    verification_reference: str | None = Field(default=None, max_length=200)
    status: PolicyStatus | None = None


class PolicyOut(ORMModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    insurer_id: uuid.UUID | None = None
    insurer_name_text: str | None = None
    policy_number: str
    policy_type: PolicyType
    coverage_class: PolicyCoverageClass
    policyholder_patient_id: uuid.UUID | None = None
    holder_name: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    sum_insured: Decimal | None = None
    currency: str
    coverage_details: dict[str, Any]
    coverage_source: CoverageSource
    coverage_verified_at: datetime | None = None
    verification_reference: str | None = None
    status: PolicyStatus
    version: int
    archived_at: datetime | None = None
    coverage_confirmed: bool
    coverage_note: str
    created_at: datetime


class AyushmanCardCreate(StrictModel):
    card_number: str = Field(min_length=4, max_length=64)
    beneficiary_name: str | None = Field(default=None, max_length=200)
    family_id: str | None = Field(default=None, max_length=64)
    scheme: str = Field(default="pmjay", max_length=40)
    valid_from: date | None = None
    valid_to: date | None = None


class AyushmanCardOut(ORMModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    scheme: str
    card_number_masked: str
    beneficiary_name: str | None = None
    family_id: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    verification_status: VerificationStatus
    verification_reference: str | None = None
    created_at: datetime


class HospitalisationCreate(StrictModel):
    facility_name: str = Field(min_length=2, max_length=200)
    admission_date: date
    discharge_date: date | None = None
    reason_summary: str | None = Field(default=None, max_length=500)
    total_amount: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)

    @model_validator(mode="after")
    def _dates_consistent(self) -> HospitalisationCreate:
        if self.discharge_date and self.discharge_date < self.admission_date:
            raise ValueError("discharge_date must not precede admission_date.")
        return self


class HospitalisationOut(ORMModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    facility_name: str
    admission_date: date
    discharge_date: date | None = None
    reason_summary: str | None = None
    total_amount: Decimal | None = None
    currency: str
    created_at: datetime


class ClaimCreate(StrictModel):
    claim_number: str = Field(min_length=1, max_length=120)
    policy_id: uuid.UUID | None = None
    hospitalisation_id: uuid.UUID | None = None
    submitted_on: date | None = None
    user_reported_status: ClaimStatus = ClaimStatus.DRAFT
    notes: str | None = Field(default=None, max_length=500)


class ClaimUpdate(StrictModel):
    claim_number: str | None = Field(default=None, min_length=1, max_length=120)
    policy_id: uuid.UUID | None = None
    hospitalisation_id: uuid.UUID | None = None
    submitted_on: date | None = None
    user_reported_status: ClaimStatus | None = None
    notes: str | None = Field(default=None, max_length=500)


class ClaimOut(ORMModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    policy_id: uuid.UUID | None = None
    hospitalisation_id: uuid.UUID | None = None
    claim_number: str
    submitted_on: date | None = None
    user_reported_status: ClaimStatus
    user_status_updated_at: datetime | None = None
    insurer_verified_status: str | None = None
    insurer_verified_at: datetime | None = None
    status_is_insurer_verified: bool
    status_note: str
    notes: str | None = None
    created_at: datetime


class ClaimDocumentCreate(StrictModel):
    document_id: uuid.UUID
    kind: Literal["invoice", "discharge_summary", "policy_copy", "prescription", "other"] = "other"


class ClaimDocumentOut(ORMModel):
    id: uuid.UUID
    claim_id: uuid.UUID
    document_id: uuid.UUID
    kind: str
    created_at: datetime


# --------------------------------------------------------------------------- policy documents
class PolicyDocumentAttach(StrictModel):
    """Attach an already-uploaded document (upload stays on the documents API)."""

    document_id: uuid.UUID
    role: PolicyDocumentRole = PolicyDocumentRole.POLICY_COPY
    endorsement_reference: str | None = Field(default=None, max_length=120)


class PolicyDocumentOut(ORMModel):
    id: uuid.UUID
    policy_id: uuid.UUID
    document_id: uuid.UUID
    role: PolicyDocumentRole
    endorsement_reference: str | None = None
    added_by_user_id: uuid.UUID | None = None
    created_at: datetime
    document_scan_status: str | None = None
    content_type: str | None = None
    byte_size: int | None = None


class ExtractionTriggerRequest(StrictModel):
    """Ask for one attached policy document to be sent for AI extraction."""

    document_id: uuid.UUID


# --------------------------------------------------------------------------- insured members
class InsuredMemberCreate(StrictModel):
    patient_id: uuid.UUID
    relationship: FamilyRelationship = FamilyRelationship.OTHER
    name_on_policy: str | None = Field(default=None, max_length=200)
    date_of_birth: date | None = None
    sum_insured_share: Decimal | None = Field(default=None, ge=0)
    is_primary: bool = False


class InsuredMemberOut(ORMModel):
    id: uuid.UUID
    policy_id: uuid.UUID
    patient_id: uuid.UUID
    relationship: FamilyRelationship
    name_on_policy: str | None = None
    date_of_birth: date | None = None
    sum_insured_share: Decimal | None = None
    is_primary: bool
    created_at: datetime


# --------------------------------------------------------------------------- coverage
class CoverageFactOut(ORMModel):
    id: uuid.UUID
    field_key: str
    label: str | None = None
    value_text: str | None = None
    value_numeric: Decimal | None = None
    value_percent: Decimal | None = None
    value_boolean: bool | None = None
    unit: str | None = None
    currency: str | None = None
    source: CoverageFactSource
    verification_status: CoverageVerificationStatus
    confidence: float | None = None
    provenance: dict[str, Any]
    original: dict[str, Any]
    corrected_at: datetime | None = None
    source_document_id: uuid.UUID | None = None
    policy_version: int
    updated_at: datetime


class CoverageFactWrite(StrictModel):
    """Manually entered or corrected coverage value."""

    field_key: str = Field(min_length=2, max_length=60, pattern=r"^[a-z][a-z0-9_.]{1,59}$")
    value_text: str | None = Field(default=None, max_length=1500)
    value_numeric: Decimal | None = None
    value_percent: Decimal | None = None
    value_boolean: bool | None = None
    note: str | None = Field(default=None, max_length=300)


class CoverageOut(StrictModel):
    policy_id: uuid.UUID
    coverage_class: PolicyCoverageClass
    coverage_source: CoverageSource
    coverage_confirmed: bool
    coverage_note: str
    field_count: int
    status_counts: dict[str, int]
    insurer_verified_fields: list[str]
    unconfirmed_fields: list[str]
    has_extracted_document: bool
    policy_expired: bool
    facts: list[CoverageFactOut]


class CoverageConfirmRequest(StrictModel):
    """Confirm extracted values. Never produces an insurer verification."""

    field_keys: list[str] | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=300)


class CoverageConfirmOut(StrictModel):
    policy_id: uuid.UUID
    confirmed_fields: list[str]
    coverage: CoverageOut


# --------------------------------------------------------------------------- versions & extraction
class PolicyVersionOut(ORMModel):
    id: uuid.UUID
    version_number: int
    kind: PolicyVersionKind
    effective_from: date | None = None
    endorsement_reference: str | None = None
    change_summary: str | None = None
    source_document_id: uuid.UUID | None = None
    created_at: datetime


class ExtractionRequestOut(ORMModel):
    id: uuid.UUID
    policy_id: uuid.UUID
    document_id: uuid.UUID
    status: ExtractionRequestStatus
    contract_version: str
    extraction_id: str | None = None
    engine_version: str | None = None
    attempts: int
    error_code: str | None = None
    completed_at: datetime | None = None
    created_at: datetime


class ExtractionReceiptOut(StrictModel):
    """Safe projection of an AI receipt: no raw payload, no OCR text."""

    extraction_id: str | None = None
    status: ExtractionRequestStatus
    engine_version: str | None = None
    completed_at: datetime | None = None
    uncertainties: list[dict[str, Any]] = Field(default_factory=list)
    clause_interpretations: list[dict[str, Any]] = Field(default_factory=list)


# --------------------------------------------------------------------------- verification
class InsurerVerifyRequest(StrictModel):
    patient_authorization_reference: str = Field(min_length=4, max_length=120)
    notes: str | None = Field(default=None, max_length=300)


class InsurerVerifyOut(StrictModel):
    outcome: InsurerVerificationOutcome
    provider: str
    reference: str | None = None
    verified_fields: list[str] = Field(default_factory=list)
    discrepancies: list[dict[str, Any]] = Field(default_factory=list)
    note: str | None = None
    attempt_id: uuid.UUID
    coverage_confirmed: bool
    policy: PolicyOut


# --------------------------------------------------------------------------- detail & guidance
class PolicyDetailOut(StrictModel):
    policy: PolicyOut
    insured_members: list[InsuredMemberOut]
    documents: list[PolicyDocumentOut]
    coverage: CoverageOut
    versions: list[PolicyVersionOut]


class PolicyGuidanceOut(StrictModel):
    policy_id: uuid.UUID
    admission_type: Literal["planned", "emergency"]
    policy_summary: dict[str, Any]
    warnings: list[str]
    admission_checklist: list[dict[str, Any]]
    cashless_preauthorisation: list[str]
    insurance_desk_questions: list[str]
    required_documents: list[str]
    claim_procedure: list[str]
    contacts: list[dict[str, Any]]
    data_gaps: list[dict[str, Any]]
    insured_member_count: int
    insured_members: list[dict[str, Any]]
    is_family_floater: bool
    disclaimer: str
