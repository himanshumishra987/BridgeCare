"""Pydantic schemas for the Intelligent Longitudinal Health Timeline."""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ai_engine.schemas.common import FieldUncertainty, SourceReference
from ai_engine.schemas.reconciliation import CrossDocumentConflict, TimelineEvent


class BeforeAfterComparison(BaseModel):
    """Temporal comparison between compatible, validly dated verified observations."""

    model_config = ConfigDict(extra="forbid")

    subject_type: str  # "biomarker" or "medication"
    subject_name: str
    before_date: str
    before_value: str
    after_date: str
    after_value: str
    unit: Optional[str] = None
    change_summary: str
    anchor_event: Optional[str] = None
    causal_disclaimer: str = (
        "Temporal comparison only; sequence does not establish causation."
    )
    source_references: list[SourceReference] = Field(default_factory=list)


class LongitudinalEpisode(BaseModel):
    """A chronologically ordered care episode connecting related verified records."""

    model_config = ConfigDict(extra="forbid")

    episode_id: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    date_missing: bool = False
    date_uncertain: bool = False
    title: str
    document_types: list[str] = Field(default_factory=list)
    document_ids: list[str] = Field(default_factory=list)
    verified_events: list[TimelineEvent] = Field(default_factory=list)
    duplicate_or_repeated_notes: list[str] = Field(default_factory=list)
    linked_biomarker_trends: list[str] = Field(default_factory=list)
    linked_medications: list[str] = Field(default_factory=list)
    linked_pattern_ids: list[str] = Field(default_factory=list)
    ai_observations: list[str] = Field(default_factory=list)
    is_clinical_diagnosis: bool = False
    source_references: list[SourceReference] = Field(default_factory=list)


class LongitudinalTimelineResult(BaseModel):
    """Unified longitudinal patient-health journey built from human-verified records."""

    model_config = ConfigDict(extra="forbid")

    insufficient_data: bool = False
    source_record_ids: list[str] = Field(default_factory=list)
    episodes: list[LongitudinalEpisode] = Field(default_factory=list)
    before_after_comparisons: list[BeforeAfterComparison] = Field(default_factory=list)
    conflicts: list[CrossDocumentConflict] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    uncertainty_flags: list[FieldUncertainty] = Field(default_factory=list)
    disclaimer: str = (
        "Chronological summary and observational links only. "
        "Temporal sequence does not establish causation or clinical diagnosis."
    )
    is_clinically_verified: bool = False
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
