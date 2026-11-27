
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ai_engine.schemas.common import (
    ConfidenceScore,
    FieldUncertainty,
)


class DocumentType(str, Enum):
    LAB_REPORT = "lab_report"
    PRESCRIPTION = "prescription"
    DISCHARGE_SUMMARY = "discharge_summary"
    CLINICAL_NOTE = "clinical_note"
    AYUSH_RECORD = "ayush_record"
    INSURANCE_DOC = "insurance_doc"
    OTHER = "other"


class ClassificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_text: str = Field(min_length=1)


class ClassificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: DocumentType
    raw_document_type: Optional[str] = None
    confidence: ConfidenceScore
    uncertainty_flags: list[FieldUncertainty] = Field(
        default_factory=list
    )
    provider_used: str
    is_mock: bool
