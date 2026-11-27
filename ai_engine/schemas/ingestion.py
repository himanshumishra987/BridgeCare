
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ai_engine.schemas.common import (
    ConfidenceScore,
    DocumentMetadata,
    ExtractionMethod,
    SourceReference,
)


class IngestionRequest(BaseModel):
    """Input supplied by the trusted backend."""

    model_config = ConfigDict(extra="forbid")

    file_bytes: bytes = Field(min_length=1)
    original_filename: str
    mime_type: str


class ExtractedPage(BaseModel):
    """Text extracted from an individual document page."""

    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1)
    text: str
    extraction_method: ExtractionMethod
    ocr_confidence: Optional[ConfidenceScore] = None
    source_reference: Optional[SourceReference] = None
    error_message: Optional[str] = None


class IngestionResult(BaseModel):
    """Output of the document ingestion stage."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    metadata: Optional[DocumentMetadata] = None
    pages: list[ExtractedPage] = Field(default_factory=list)
    error_type: Optional[str] = None
    error_message: Optional[str] = None
