"""Pydantic schemas for BridgeCare Insurance Intelligence.

Covers policy identity, coverage limits, cost-sharing, exclusions, additional
benefits, claims processes, evidence provenance, clause interpretation, patient
explanations, admission guidance, and multi-source verification comparison.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from ai_engine.schemas.common import ConfidenceCategory, ConfidenceScore, FieldUncertainty, SourceReference

T = TypeVar("T")


class InsuranceVerificationStatus(str, Enum):
    """Granular verification status for insurance extracted fields and profiles.

    Patient confirmation is strictly separated from insurer verification.
    """

    EXTRACTED = "EXTRACTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    PATIENT_CONFIRMED = "PATIENT_CONFIRMED"
    DISCREPANCY = "DISCREPANCY"
    INSURER_VERIFIED = "INSURER_VERIFIED"


class PolicyType(str, Enum):
    """Categorization of health insurance policies."""

    INDIVIDUAL = "individual"
    FAMILY_FLOATER = "family_floater"
    GROUP = "group"
    SENIOR_CITIZEN = "senior_citizen"
    CRITICAL_ILLNESS = "critical_illness"
    TOP_UP = "top_up"
    OTHER = "other"


class InsuranceDocumentType(str, Enum):
    """Supported insurance document classifications."""

    POLICY_SCHEDULE = "policy_schedule"
    COMPLETE_POLICY_WORDING = "complete_policy_wording"
    BENEFIT_SUMMARY = "benefit_summary"
    ENDORSEMENT_OR_AMENDMENT = "endorsement_or_amendment"
    CLAIM_OR_PREAUTH_DOCUMENT = "claim_or_preauth_document"
    OTHER_INSURANCE_DOC = "other_insurance_doc"


class InsuranceField(BaseModel, Generic[T]):
    """Strictly validated, evidence-backed container for any extracted insurance data point."""

    model_config = ConfigDict(extra="forbid")

    value: Optional[T] = None
    original_policy_wording: Optional[str] = None
    currency: Optional[str] = None
    unit: Optional[str] = None
    source_document_id: Optional[str] = None
    page_number: Optional[int] = None
    clause_reference: Optional[str] = None
    supporting_excerpt: Optional[str] = None
    confidence: Optional[ConfidenceScore] = None
    verification_status: InsuranceVerificationStatus = InsuranceVerificationStatus.EXTRACTED
    verification_source: str = "ai_extraction"  # "ai_extraction" | "patient" | "insurer_backend"
    is_ambiguous: bool = False
    ambiguity_reason: Optional[str] = None
    conflicting_values: list[str] = Field(default_factory=list)


class InsuredMember(BaseModel):
    """Insured individual within an individual or family floater policy."""

    model_config = ConfigDict(extra="forbid")

    member_name: str
    member_id: Optional[str] = None
    relationship_to_policyholder: Optional[str] = None
    age: Optional[int] = None
    date_of_birth: Optional[str] = None
    individual_sum_insured: Optional[float] = None
    pre_existing_conditions: list[str] = Field(default_factory=list)
    waiting_period_months: Optional[int] = None
    verification_status: InsuranceVerificationStatus = InsuranceVerificationStatus.EXTRACTED
    source_reference: Optional[SourceReference] = None


class DiseaseSublimit(BaseModel):
    """Sub-limit capping coverage for a specific medical condition or procedure."""

    model_config = ConfigDict(extra="forbid")

    disease_or_procedure: str
    limit_amount: Optional[float] = None
    limit_percentage: Optional[float] = None
    limit_description: str
    currency: str = "INR"
    clause_reference: Optional[str] = None
    source_reference: Optional[SourceReference] = None
    is_ambiguous: bool = False


class WaitingPeriodClause(BaseModel):
    """Waiting period restriction before specific benefits activate."""

    model_config = ConfigDict(extra="forbid")

    category: str  # "initial_waiting_period", "specific_disease_waiting_period", "pre_existing_disease_waiting_period"
    duration_months: Optional[int] = None
    duration_days: Optional[int] = None
    applicable_conditions: list[str] = Field(default_factory=list)
    description: str
    clause_reference: Optional[str] = None
    source_reference: Optional[SourceReference] = None


class InsuranceClauseItem(BaseModel):
    """Detailed policy clause such as an exclusion, restriction, or limitation."""

    model_config = ConfigDict(extra="forbid")

    title: str
    description: str
    category: str  # "permanent_exclusion", "specific_disease_exclusion", "treatment_limitation", "general_condition"
    clause_reference: Optional[str] = None
    source_reference: Optional[SourceReference] = None
    is_conditional: bool = False
    conditions: list[str] = Field(default_factory=list)


class PolicyIdentityCategory(BaseModel):
    """Category A: Policy Identification & Member Registry."""

    model_config = ConfigDict(extra="forbid")

    insurance_provider: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    policy_number: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    policyholder_name: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    insured_members: list[InsuredMember] = Field(default_factory=list)
    policy_type: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    commencement_date: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    expiry_date: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    policy_status: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    document_category: InsuranceDocumentType = InsuranceDocumentType.POLICY_SCHEDULE


class CoverageInformationCategory(BaseModel):
    """Category B: Base and Ancillary Coverage Information."""

    model_config = ConfigDict(extra="forbid")

    sum_insured: InsuranceField[float] = Field(default_factory=lambda: InsuranceField[float]())
    coverage_scope: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())  # individual vs shared_floater
    room_rent_limits: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    icu_limits: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    hospitalization_expenses: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    doctor_surgeon_fees: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    nursing_ot_charges: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    pre_hospitalization_expenses: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    pre_hospitalization_days: InsuranceField[int] = Field(default_factory=lambda: InsuranceField[int]())
    post_hospitalization_expenses: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    post_hospitalization_days: InsuranceField[int] = Field(default_factory=lambda: InsuranceField[int]())
    day_care_procedures: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    ambulance_coverage: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    medicine_pharmacy_coverage: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    diagnostics: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    consumables: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    disease_specific_sublimits: list[DiseaseSublimit] = Field(default_factory=list)


class CostSharingCategory(BaseModel):
    """Category C: Cost-Sharing, Deductibles, and Policy Restrictions."""

    model_config = ConfigDict(extra="forbid")

    co_payment: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    co_payment_percentage: Optional[float] = None
    deductibles: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    deductible_amount: Optional[float] = None
    room_category_restrictions: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    waiting_periods: list[WaitingPeriodClause] = Field(default_factory=list)
    pre_existing_disease_conditions: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    permanent_exclusions: list[InsuranceClauseItem] = Field(default_factory=list)
    disease_specific_exclusions: list[InsuranceClauseItem] = Field(default_factory=list)
    treatment_specific_limitations: list[InsuranceClauseItem] = Field(default_factory=list)


class AdditionalBenefitsCategory(BaseModel):
    """Category D: Value-Added and Additional Policy Benefits."""

    model_config = ConfigDict(extra="forbid")

    restoration_benefit: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    no_claim_bonus: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    ayush_coverage: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    maternity_coverage: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    health_checkups: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    domiciliary_hospitalization: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    organ_donor_expenses: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())


class ClaimsInformationCategory(BaseModel):
    """Category E: Third Party Administrator (TPA) & Claims Protocols."""

    model_config = ConfigDict(extra="forbid")

    tpa_details: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    insurer_helpline: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    cashless_process: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    reimbursement_process: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    claim_notification_requirements: InsuranceField[str] = Field(default_factory=lambda: InsuranceField[str]())
    required_claim_documents: list[str] = Field(default_factory=list)


class InsurancePolicyProfile(BaseModel):
    """Unified evidence-backed structured insurance policy profile."""

    model_config = ConfigDict(extra="forbid")

    document_id: Optional[str] = None
    identity: PolicyIdentityCategory = Field(default_factory=PolicyIdentityCategory)
    coverage: CoverageInformationCategory = Field(default_factory=CoverageInformationCategory)
    cost_sharing: CostSharingCategory = Field(default_factory=CostSharingCategory)
    additional_benefits: AdditionalBenefitsCategory = Field(default_factory=AdditionalBenefitsCategory)
    claims: ClaimsInformationCategory = Field(default_factory=ClaimsInformationCategory)

    missing_fields: list[str] = Field(default_factory=list)
    ambiguous_fields: list[str] = Field(default_factory=list)
    uncertainty_flags: list[FieldUncertainty] = Field(default_factory=list)
    overall_confidence: Optional[ConfidenceScore] = None
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InsuranceClauseInterpretation(BaseModel):
    """Semantic breakdown of a specific policy clause or provision."""

    model_config = ConfigDict(extra="forbid")

    clause_name: str
    original_clause_text: str
    clause_reference: Optional[str] = None
    plain_english_meaning: str
    applicable_conditions: list[str] = Field(default_factory=list)
    restrictions_and_limitations: list[str] = Field(default_factory=list)
    potential_out_of_pocket_risks: list[str] = Field(default_factory=list)
    recommended_clarifications_with_insurer: list[str] = Field(default_factory=list)
    is_conditional_coverage: bool = True
    distinctions: dict[str, str] = Field(default_factory=dict)
    source_reference: Optional[SourceReference] = None


class InsurancePatientExplanation(BaseModel):
    """Patient-facing grounded explanation of key insurance concepts."""

    model_config = ConfigDict(extra="forbid")

    topic: str  # "room_rent_restrictions", "co_payment", "deductibles", "waiting_periods", "exclusions", "cashless", "reimbursement", "pre_post_hospitalization"
    title: str
    patient_explanation: str
    key_policy_rules: list[str] = Field(default_factory=list)
    how_it_affects_your_bill: str
    supporting_clauses: list[str] = Field(default_factory=list)
    source_references: list[SourceReference] = Field(default_factory=list)
    no_guarantee_disclaimer: str = (
        "This explanation is for educational purposes based on documented policy clauses. "
        "It does not constitute a guaranteed claim-approval prediction. Final claim settlement "
        "depends on hospital billing, clinical diagnosis, and the insurer's adjudication."
    )


class HospitalAdmissionGuidance(BaseModel):
    """Actionable checklist and questions for hospital admission."""

    model_config = ConfigDict(extra="forbid")

    admission_type: str  # "planned" or "emergency"
    admission_checklist: list[str] = Field(default_factory=list)
    insurance_desk_questions: list[str] = Field(default_factory=list)
    documents_to_carry: list[str] = Field(default_factory=list)
    cashless_preauth_steps: list[str] = Field(default_factory=list)
    coverage_restrictions_to_check: list[str] = Field(default_factory=list)
    reimbursement_preparation_guidance: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "Guidance is derived from documented policy terms. Always confirm cashless network "
        "status and pre-authorization requirements directly with the hospital TPA desk."
    )


class FieldDiscrepancy(BaseModel):
    """Detailed discrepancy comparison for an insurance policy attribute across sources."""

    model_config = ConfigDict(extra="forbid")

    field_name: str
    pdf_extracted_value: Optional[Any] = None
    patient_entered_value: Optional[Any] = None
    insurer_confirmed_value: Optional[Any] = None
    has_discrepancy: bool
    status: InsuranceVerificationStatus
    discrepancy_explanation: Optional[str] = None


class InsuranceDiscrepancyReport(BaseModel):
    """Multi-source discrepancy report comparing PDF extractions, patient confirmations, and insurer verifications."""

    model_config = ConfigDict(extra="forbid")

    policy_number: str
    discrepancies: list[FieldDiscrepancy] = Field(default_factory=list)
    unverified_fields_count: int = 0
    patient_confirmed_count: int = 0
    insurer_verified_count: int = 0
    discrepancy_count: int = 0
    overall_status: InsuranceVerificationStatus
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class InsuranceExtractionRequest(BaseModel):
    """Request contract for extracting an insurance policy document."""

    model_config = ConfigDict(extra="forbid")

    file_bytes: bytes
    original_filename: str = "policy.pdf"
    mime_type: Optional[str] = None
    document_id: Optional[str] = None
    target_member_name: Optional[str] = None


class InsuranceExtractionResponse(BaseModel):
    """Verification-ready response contract for insurance extraction."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    verification_status: InsuranceVerificationStatus = InsuranceVerificationStatus.NEEDS_REVIEW
    is_insurer_verified: bool = False
    policy_profile: Optional[InsurancePolicyProfile] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
