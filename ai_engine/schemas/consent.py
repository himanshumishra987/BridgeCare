"""Pydantic schemas for Consent-Aware Health Information Sharing."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from ai_engine.languages import LanguagePreference
from ai_engine.schemas.assistant import AssistantChatResponse
from ai_engine.schemas.summary import SummaryResult


class ConsentStatus(str, Enum):
    """Lifecycle state of a patient's sharing consent."""

    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    PENDING = "pending"
    DENIED = "denied"


class SharingPurpose(str, Enum):
    """Explicit purpose for which health records may be shared."""

    CLINICAL_CONSULTATION = "clinical_consultation"
    EMERGENCY_CARE = "emergency_care"
    SECOND_OPINION = "second_opinion"
    INSURANCE_CLAIM = "insurance_claim"
    CAREGIVER_VIEW = "caregiver_view"
    PATIENT_SELF_REVIEW = "patient_self_review"


class PermittedDataCategory(str, Enum):
    """Granular data categories permitted by a consent grant."""

    LAB_RESULTS = "lab_results"
    MEDICATIONS = "medications"
    CLINICAL_EVENTS = "clinical_events"
    DOCUMENT_METADATA = "document_metadata"
    SUMMARIES = "summaries"


class ConsentGrant(BaseModel):
    """Explicit authorization decision supplied by the trusted backend."""

    model_config = ConfigDict(extra="forbid")

    consent_id: str = Field(min_length=1)
    patient_id: str = Field(min_length=1)
    recipient_id: str = Field(min_length=1)
    purpose: SharingPurpose
    status: ConsentStatus
    permitted_document_ids: list[str] = Field(default_factory=list)
    permitted_categories: list[PermittedDataCategory] = Field(default_factory=list)
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    issued_by: str = "trusted_backend"


class ConsentAuditMetadata(BaseModel):
    """Privacy-safe audit metadata recording authorization and filtering outcomes."""

    model_config = ConfigDict(extra="forbid")

    consent_id: Optional[str] = None
    patient_id: str
    recipient_id: str
    purpose: SharingPurpose
    decision: str  # "allowed" or "denied"
    denial_code: Optional[str] = None
    denial_reason: Optional[str] = None
    included_document_ids: list[str] = Field(default_factory=list)
    excluded_record_count: int = 0
    excluded_reasons: list[str] = Field(default_factory=list)
    permitted_categories: list[PermittedDataCategory] = Field(default_factory=list)
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ConsentShareRequest(BaseModel):
    """Request to generate a consent-filtered medical summary."""

    model_config = ConfigDict(extra="forbid")

    patient_id: str = Field(min_length=1)
    recipient_id: str = Field(min_length=1)
    purpose: SharingPurpose
    consent_id: Optional[str] = None
    consent: Optional[ConsentGrant] = None
    records: list[dict[str, Any]] = Field(default_factory=list)
    language: LanguagePreference = Field(
        default_factory=lambda: LanguagePreference(language_code="en")
    )


class ConsentShareResponse(BaseModel):
    """Response for consent-aware shared summary generation."""

    model_config = ConfigDict(extra="forbid")

    authorized: bool
    denial_code: Optional[str] = None
    denial_reason: Optional[str] = None
    summary: Optional[SummaryResult] = None
    audit: ConsentAuditMetadata
    response_language: str
    response_language_name: str
    is_clinically_verified: bool = False


class ConsentQuestionRequest(BaseModel):
    """Request to answer a patient/recipient question over consent-filtered records."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    patient_id: str = Field(min_length=1)
    recipient_id: str = Field(min_length=1)
    purpose: SharingPurpose
    consent_id: Optional[str] = None
    consent: Optional[ConsentGrant] = None
    records: list[dict[str, Any]] = Field(default_factory=list)
    language: LanguagePreference = Field(
        default_factory=lambda: LanguagePreference(language_code="en")
    )


class ConsentQuestionResponse(BaseModel):
    """Response for consent-aware conversational Q&A."""

    model_config = ConfigDict(extra="forbid")

    authorized: bool
    denial_code: Optional[str] = None
    denial_reason: Optional[str] = None
    assistant_response: Optional[AssistantChatResponse] = None
    audit: ConsentAuditMetadata
    response_language: str
    response_language_name: str
    is_clinically_verified: bool = False
