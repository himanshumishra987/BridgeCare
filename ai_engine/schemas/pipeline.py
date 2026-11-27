"""Pydantic schemas for the end-to-end AI document processing pipeline."""

from typing import Optional

from pydantic import BaseModel, ConfigDict

from ai_engine.schemas.classification import ClassificationResult
from ai_engine.schemas.common import VerificationStatus
from ai_engine.schemas.extraction import ExtractionResult
from ai_engine.schemas.ingestion import IngestionResult
from ai_engine.schemas.insurance import InsurancePolicyProfile


class PipelineResult(BaseModel):
    """Verification-ready output of the Ingestion -> Classification -> Extraction pipeline."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    verification_status: VerificationStatus = VerificationStatus.PENDING_REVIEW
    is_clinically_verified: bool = False
    ingestion: Optional[IngestionResult] = None
    classification: Optional[ClassificationResult] = None
    extraction: Optional[ExtractionResult] = None
    insurance_extraction: Optional[InsurancePolicyProfile] = None
    stage_failed: Optional[str] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
