"""Pydantic schemas for Cross-Document Medical Intelligence and Reconciliation."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from ai_engine.schemas.common import FieldUncertainty, SourceReference


class TrendDirection(str, Enum):
    """Longitudinal direction of a biomarker across comparable measurements."""

    INCREASING = "increasing"
    DECREASING = "decreasing"
    STABLE = "stable"
    FLUCTUATING = "fluctuating"
    INSUFFICIENT_DATA = "insufficient_data"


class BiomarkerDataPoint(BaseModel):
    """A single verified biomarker observation linked to its source document."""

    model_config = ConfigDict(extra="forbid")

    document_id: Optional[str] = None
    recorded_date: Optional[str] = None
    value: str
    numeric_value: Optional[float] = None
    unit: Optional[str] = None
    reference_range: Optional[str] = None
    abnormal_flag: Optional[str] = None
    source_reference: Optional[SourceReference] = None


class BiomarkerTrend(BaseModel):
    """Reconciled longitudinal trend for a single biomarker across verified records."""

    model_config = ConfigDict(extra="forbid")

    biomarker_name: str
    normalized_unit: Optional[str] = None
    trend_direction: TrendDirection
    is_comparable: bool
    data_points: list[BiomarkerDataPoint] = Field(default_factory=list)
    summary_note: str


class MedicationReconciliationStatus(str, Enum):
    """Reconciliation status of a medication across multiple verified records."""

    SINGLE_RECORD = "single_record"
    CONSISTENT = "consistent"
    DOSE_OR_FREQUENCY_CHANGED = "dose_or_frequency_changed"
    DUPLICATE_INGREDIENT = "duplicate_ingredient"
    CONFLICTING = "conflicting"


class ReconciledMedication(BaseModel):
    """Reconciled medication history and regimen comparison across verified documents."""

    model_config = ConfigDict(extra="forbid")

    medication_key: str
    brand_names: list[str] = Field(default_factory=list)
    generic_ingredients: list[str] = Field(default_factory=list)
    status: MedicationReconciliationStatus
    regimens: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    source_references: list[SourceReference] = Field(default_factory=list)


class ConflictSeverity(str, Enum):
    """Severity level for cross-document medical data conflicts."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CrossDocumentConflict(BaseModel):
    """Structured conflict detected across two or more verified records."""

    model_config = ConfigDict(extra="forbid")

    conflict_type: str
    field_name: str
    severity: ConflictSeverity
    description: str
    document_ids: list[str] = Field(default_factory=list)
    source_references: list[SourceReference] = Field(default_factory=list)


class TimelineEvent(BaseModel):
    """Chronological clinical or document event grounded in a verified record."""

    model_config = ConfigDict(extra="forbid")

    event_date: Optional[str] = None
    date_missing: bool = False
    event_type: str
    description: str
    document_id: Optional[str] = None
    document_type: Optional[str] = None
    source_reference: Optional[SourceReference] = None


class ReconciliationResult(BaseModel):
    """Output of the Cross-Document Medical Intelligence and Reconciliation engine."""

    model_config = ConfigDict(extra="forbid")

    insufficient_data: bool = False
    source_record_ids: list[str] = Field(default_factory=list)
    biomarker_trends: list[BiomarkerTrend] = Field(default_factory=list)
    reconciled_medications: list[ReconciledMedication] = Field(default_factory=list)
    conflicts: list[CrossDocumentConflict] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    uncertainty_flags: list[FieldUncertainty] = Field(default_factory=list)
    is_clinically_verified: bool = False
    reconciled_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
