from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ai_engine.schemas.common import (
    ConfidenceScore,
    FieldUncertainty,
    SourceReference,
)
from ai_engine.schemas.classification import DocumentType


class ExtractedBiomarker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: str
    numeric_value: Optional[float] = None
    unit: Optional[str] = None
    reference_range: Optional[str] = None
    abnormal_flag: Optional[str] = None
    source_reference: Optional[SourceReference] = None
    confidence: Optional[ConfidenceScore] = None


class ExtractedMedication(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_name: Optional[str] = None
    generic_ingredients: list[str] = Field(default_factory=list)
    strength: Optional[str] = None
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    duration: Optional[str] = None
    instructions: Optional[str] = None
    source_reference: Optional[SourceReference] = None
    confidence: Optional[ConfidenceScore] = None


class ExtractedClinicalEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str
    description: str
    event_date: Optional[str] = None
    source_reference: Optional[SourceReference] = None
    confidence: Optional[ConfidenceScore] = None


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: DocumentType
    document_date: Optional[str] = None
    hospital_or_lab_name: Optional[str] = None
    doctor_name: Optional[str] = None
    patient_name: Optional[str] = None

    biomarkers: list[ExtractedBiomarker] = Field(default_factory=list)
    medications: list[ExtractedMedication] = Field(default_factory=list)
    clinical_events: list[ExtractedClinicalEvent] = Field(default_factory=list)

    missing_fields: list[str] = Field(default_factory=list)
    uncertainty_flags: list[FieldUncertainty] = Field(default_factory=list)
    overall_confidence: Optional[ConfidenceScore] = None
