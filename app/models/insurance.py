"""Insurance, policy, government-scheme, hospitalisation, claim and claim-document models.

Nothing in this module asserts that cover exists. ``coverage_source`` records
*how* the coverage information was obtained, and only ``INSURER_VERIFIED``
(with a verification reference) is presented as confirmed.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSONColumn, Base, TimestampMixin, UUIDPrimaryKeyMixin
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
    enum_type,
)


class Insurer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "insurers"

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    short_name: Mapped[str | None] = mapped_column(String(80))
    regulator_reference: Mapped[str | None] = mapped_column(String(120))
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="IN")


class InsurancePolicy(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "insurance_policies"
    __table_args__ = (Index("ix_insurance_policies_patient", "patient_id", "status"),)

    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    insurer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("insurers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    insurer_name_text: Mapped[str | None] = mapped_column(String(200))
    policy_number: Mapped[str] = mapped_column(String(120), nullable=False)
    policy_type: Mapped[PolicyType] = mapped_column(
        enum_type(PolicyType, 30), nullable=False, default=PolicyType.HEALTH
    )
    holder_name: Mapped[str | None] = mapped_column(String(200))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    sum_insured: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    coverage_details: Mapped[dict[str, Any]] = mapped_column(JSONColumn, nullable=False, default=dict)
    coverage_source: Mapped[CoverageSource] = mapped_column(
        enum_type(CoverageSource, 30), nullable=False, default=CoverageSource.USER_ENTERED
    )
    coverage_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_reference: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[PolicyStatus] = mapped_column(
        enum_type(PolicyStatus, 20), nullable=False, default=PolicyStatus.UNKNOWN
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Family floaters are one policy with several insured members, never copies.
    coverage_class: Mapped[PolicyCoverageClass] = mapped_column(
        enum_type(PolicyCoverageClass, 30),
        nullable=False,
        default=PolicyCoverageClass.INDIVIDUAL,
    )
    policyholder_patient_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    @property
    def coverage_confirmed(self) -> bool:
        """True only when an insurer-side verification reference exists."""
        return (
            self.coverage_source == CoverageSource.INSURER_VERIFIED
            and bool(self.verification_reference)
        )

    @property
    def coverage_note(self) -> str:
        if self.coverage_confirmed:
            return "Coverage confirmed against the insurer verification reference on file."
        return (
            "Coverage information is as entered by the user and has not been verified "
            "by the insurer."
        )


class AyushmanCard(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Ayushman Bharat (PM-JAY) card details as entered by the beneficiary."""

    __tablename__ = "ayushman_cards"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scheme: Mapped[str] = mapped_column(String(40), nullable=False, default="pmjay")
    card_number: Mapped[str] = mapped_column(String(64), nullable=False)
    beneficiary_name: Mapped[str | None] = mapped_column(String(200))
    family_id: Mapped[str | None] = mapped_column(String(64))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        enum_type(VerificationStatus, 20),
        nullable=False,
        default=VerificationStatus.UNVERIFIED,
    )
    verification_reference: Mapped[str | None] = mapped_column(String(200))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    @property
    def card_number_masked(self) -> str:
        digits = (self.card_number or "").strip()
        if len(digits) <= 4:
            return "*" * len(digits)
        return "*" * (len(digits) - 4) + digits[-4:]


class Hospitalisation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "hospitalisations"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    facility_name: Mapped[str] = mapped_column(String(200), nullable=False)
    admission_date: Mapped[date] = mapped_column(Date, nullable=False)
    discharge_date: Mapped[date | None] = mapped_column(Date)
    reason_summary: Mapped[str | None] = mapped_column(String(500))
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class Claim(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A claim with a *user-reported* status only.

    ``insurer_verified_status`` stays NULL unless a supported insurer
    integration writes it, which is why API responses always carry
    ``status_is_insurer_verified``.
    """

    __tablename__ = "claims"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    policy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("insurance_policies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    hospitalisation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("hospitalisations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    claim_number: Mapped[str] = mapped_column(String(120), nullable=False)
    submitted_on: Mapped[date | None] = mapped_column(Date)
    user_reported_status: Mapped[ClaimStatus] = mapped_column(
        enum_type(ClaimStatus, 30), nullable=False, default=ClaimStatus.DRAFT
    )
    user_status_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    insurer_verified_status: Mapped[str | None] = mapped_column(String(64))
    insurer_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    @property
    def status_is_insurer_verified(self) -> bool:
        """False for every claim status a user typed in."""
        return self.insurer_verified_status is not None

    @property
    def status_note(self) -> str:
        if self.status_is_insurer_verified:
            return "Status confirmed by the insurer integration."
        return (
            "This status is as reported by the user and has not been confirmed by "
            "the insurer."
        )


class ClaimDocument(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "claim_documents"
    __table_args__ = (
        UniqueConstraint("claim_id", "document_id", name="uq_claim_documents_claim_document"),
    )

    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="other")


class InsurancePolicyDocument(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Attaches an already-uploaded document to a policy.

    No bytes are stored twice: this is the join between the existing secure
    document pipeline and the policy it evidences.
    """

    __tablename__ = "insurance_policy_documents"
    __table_args__ = (
        UniqueConstraint(
            "policy_id", "document_id", name="uq_insurance_policy_documents_policy_document"
        ),
    )

    policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("insurance_policies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[PolicyDocumentRole] = mapped_column(
        enum_type(PolicyDocumentRole, 30),
        nullable=False,
        default=PolicyDocumentRole.POLICY_COPY,
    )
    endorsement_reference: Mapped[str | None] = mapped_column(String(120))
    added_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class InsurancePolicyVersion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Append-only policy history: creation, edits, extractions, endorsements."""

    __tablename__ = "insurance_policy_versions"
    __table_args__ = (
        UniqueConstraint(
            "policy_id", "version_number", name="uq_insurance_policy_versions_policy_version"
        ),
    )

    policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("insurance_policies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[PolicyVersionKind] = mapped_column(
        enum_type(PolicyVersionKind, 30), nullable=False
    )
    effective_from: Mapped[date | None] = mapped_column(Date)
    endorsement_reference: Mapped[str | None] = mapped_column(String(120))
    change_summary: Mapped[str | None] = mapped_column(String(500))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONColumn, nullable=False, default=dict)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class InsuranceInsuredMember(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One person covered by a policy.

    Membership is an explicit association, created only by a user who already has
    write access to the policy's patient and who is that patient's guardian (or the
    patient themselves). Kinship alone never creates a row here.
    """

    __tablename__ = "insurance_insured_members"
    __table_args__ = (
        UniqueConstraint(
            "policy_id", "patient_id", name="uq_insurance_insured_members_policy_patient"
        ),
    )

    policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("insurance_policies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relationship: Mapped[FamilyRelationship] = mapped_column(
        enum_type(FamilyRelationship, 20), nullable=False, default=FamilyRelationship.OTHER
    )
    name_on_policy: Mapped[str | None] = mapped_column(String(200))
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    sum_insured_share: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    added_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class InsuranceCoverageFact(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One coverage value with its provenance and verification state.

    ``original`` is written once and never replaced, so a patient correction
    cannot destroy what the extractor read. Superseded values stay in the table
    with ``is_active = False`` rather than being deleted.
    """

    __tablename__ = "insurance_coverage_facts"
    __table_args__ = (
        Index("ix_insurance_coverage_facts_policy_field", "policy_id", "field_key"),
    )

    policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("insurance_policies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    field_key: Mapped[str] = mapped_column(String(60), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))
    value_text: Mapped[str | None] = mapped_column(String(500))
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    value_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    value_boolean: Mapped[bool | None] = mapped_column(Boolean)
    unit: Mapped[str | None] = mapped_column(String(24))
    currency: Mapped[str | None] = mapped_column(String(3))
    source: Mapped[CoverageFactSource] = mapped_column(
        enum_type(CoverageFactSource, 20), nullable=False
    )
    verification_status: Mapped[CoverageVerificationStatus] = mapped_column(
        enum_type(CoverageVerificationStatus, 30),
        nullable=False,
        default=CoverageVerificationStatus.NEEDS_REVIEW,
        index=True,
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONColumn, nullable=False, default=dict)
    original: Mapped[dict[str, Any]] = mapped_column(JSONColumn, nullable=False, default=dict)
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    corrected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class InsuranceExtractionRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Orchestration record for one policy document sent for AI extraction."""

    __tablename__ = "insurance_extraction_requests"
    __table_args__ = (
        Index("ix_insurance_extraction_requests_policy_status", "policy_id", "status"),
    )

    policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("insurance_policies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[ExtractionRequestStatus] = mapped_column(
        enum_type(ExtractionRequestStatus, 20),
        nullable=False,
        default=ExtractionRequestStatus.QUEUED,
    )
    contract_version: Mapped[str] = mapped_column(String(40), nullable=False)
    extraction_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    engine_version: Mapped[str | None] = mapped_column(String(40))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(60))
    error_detail: Mapped[str | None] = mapped_column(String(500))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Raw AI output kept as a receipt: interpretations, uncertainties, provenance.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONColumn, nullable=False, default=dict)


class InsurerVerificationAttempt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Audit trail for the insurer verification boundary.

    A row here records that verification was attempted and what came back; it is
    never created by a patient-facing lookup and never substitutes for one.
    """

    __tablename__ = "insurer_verification_attempts"

    policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("insurance_policies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    outcome: Mapped[InsurerVerificationOutcome] = mapped_column(
        enum_type(InsurerVerificationOutcome, 30), nullable=False
    )
    patient_authorization_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    verification_reference: Mapped[str | None] = mapped_column(String(200))
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discrepancy_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    details: Mapped[dict[str, Any]] = mapped_column(JSONColumn, nullable=False, default=dict)
