
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ExtractionMethod(str, Enum):
    DIGITAL = "digital"
    OCR = "ocr"
    MIXED = "mixed"


class ConfidenceCategory(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNCERTAIN = "uncertain"


class VerificationStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    VERIFIED = "verified"
    EDITED_VERIFIED = "edited_verified"
    REJECTED = "rejected"


class ConfidenceScore(BaseModel):
    """A confidence value with an explicit source."""

    model_config = ConfigDict(extra="forbid")

    score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    source: str
    category: ConfidenceCategory


class SourceReference(BaseModel):
    """Links extracted information to its original document location."""

    model_config = ConfigDict(extra="forbid")

    document_id: Optional[str] = None
    page_number: int = Field(ge=1)
    excerpt: str = Field(min_length=1)
    field_name: Optional[str] = None


class FieldUncertainty(BaseModel):
    """Describes missing, uncertain or conflicting information."""

    model_config = ConfigDict(extra="forbid")

    field_name: str
    reason: str
    source_reference: Optional[SourceReference] = None


class DocumentMetadata(BaseModel):
    """Metadata about an uploaded medical document."""

    model_config = ConfigDict(extra="forbid")

    original_filename: str
    mime_type: str
    file_size_bytes: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    page_count: int = Field(ge=1)
    extraction_method: ExtractionMethod
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
