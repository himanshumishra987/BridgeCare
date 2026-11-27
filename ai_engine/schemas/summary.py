"""Pydantic schemas for grounded medical summary generation."""

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_engine.schemas.common import (
    ConfidenceScore,
    FieldUncertainty,
    SourceReference,
    VerificationStatus,
)

APPROVED_VERIFICATION_STATUSES = frozenset(
    {VerificationStatus.VERIFIED, VerificationStatus.EDITED_VERIFIED}
)


class VerifiedRecordInput(BaseModel):
    """Contract for an explicitly human-verified medical record passed to summary generation."""

    model_config = ConfigDict(extra="allow")

    document_id: Optional[str] = None
    verification_status: VerificationStatus
    document_type: Optional[str] = None
    document_date: Optional[str] = None
    hospital_or_lab_name: Optional[str] = None
    doctor_name: Optional[str] = None
    patient_name: Optional[str] = None
    biomarkers: list[dict[str, Any]] = Field(default_factory=list)
    medications: list[dict[str, Any]] = Field(default_factory=list)
    clinical_events: list[dict[str, Any]] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    uncertainty_flags: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("verification_status")
    @classmethod
    def must_be_human_verified(cls, v: VerificationStatus) -> VerificationStatus:
        """Reject pending_review, rejected, or unapproved verification statuses."""
        if v not in APPROVED_VERIFICATION_STATUSES:
            raise ValueError(
                f"Record verification_status '{v.value}' is not approved for summary generation. "
                "Only 'verified' and 'edited_verified' records are permitted."
            )
        return v


class SummaryResult(BaseModel):
    """Structured, grounded summary generated strictly from human-verified records."""

    model_config = ConfigDict(extra="forbid")

    insufficient_data: bool = False
    patient_friendly_summary: str = Field(min_length=1)
    doctor_ready_summary: str = Field(min_length=1)
    key_findings: list[str] = Field(default_factory=list)
    source_references: list[SourceReference] = Field(default_factory=list)
    source_record_ids: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    conflicting_information: list[str] = Field(default_factory=list)
    uncertainty_flags: list[FieldUncertainty] = Field(default_factory=list)
    confidence: ConfidenceScore
    provider_used: str
    response_language: str = "en"
    response_language_name: str = "English"
    is_mock: bool = False
    is_clinically_verified: bool = False
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
