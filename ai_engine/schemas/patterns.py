"""Pydantic schemas for Intelligent Health Pattern Identification."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ai_engine.schemas.common import (
    ConfidenceScore,
    FieldUncertainty,
    SourceReference,
)


class PatternSeverity(str, Enum):
    """Review priority / severity for an identified health pattern."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class PatternCategory(str, Enum):
    """Category of observational health pattern."""

    REFERENCE_RANGE_DEVIATION = "reference_range_deviation"
    REPEATED_ABNORMALITY = "repeated_abnormality"
    RAPID_OR_MEANINGFUL_CHANGE = "rapid_or_meaningful_change"
    BIOMARKER_RELATIONSHIP = "biomarker_relationship"
    MEDICATION_REVIEW = "medication_review"


class HealthPattern(BaseModel):
    """A single structured observational pattern flagged for human/clinician review."""

    model_config = ConfigDict(extra="forbid")

    pattern_id: str
    category: PatternCategory
    title: str
    severity: PatternSeverity
    explanation: str
    observation_only: bool = True
    is_clinical_diagnosis: bool = False
    related_biomarkers: list[str] = Field(default_factory=list)
    related_medications: list[str] = Field(default_factory=list)
    confidence: ConfidenceScore
    uncertainty_flags: list[FieldUncertainty] = Field(default_factory=list)
    source_references: list[SourceReference] = Field(default_factory=list)


class PatternIdentificationResult(BaseModel):
    """Output of the Intelligent Health Pattern Identification engine."""

    model_config = ConfigDict(extra="forbid")

    insufficient_data: bool = False
    source_record_ids: list[str] = Field(default_factory=list)
    patterns: list[HealthPattern] = Field(default_factory=list)
    uncertainty_flags: list[FieldUncertainty] = Field(default_factory=list)
    disclaimer: str = (
        "Observational patterns only. Not a clinical diagnosis, medical advice, "
        "or treatment recommendation. Requires clinician review."
    )
    is_clinically_verified: bool = False
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
