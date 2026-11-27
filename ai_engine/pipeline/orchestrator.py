"""End-to-end asynchronous AI document processing orchestrator."""

import logging
from typing import Optional

from pydantic import ValidationError

from ai_engine.ingestion.engine import DocumentIngestionEngine
from ai_engine.insurance.engine import InsuranceIntelligenceEngine
from ai_engine.pipeline.provenance import validate_extraction_provenance
from ai_engine.providers.base import AIProvider
from ai_engine.providers.config import AIProviderConfig
from ai_engine.providers.exceptions import AIProviderError
from ai_engine.providers.factory import get_ai_provider
from ai_engine.schemas.classification import ClassificationResult, DocumentType
from ai_engine.schemas.common import VerificationStatus
from ai_engine.schemas.extraction import ExtractionResult
from ai_engine.schemas.ingestion import IngestionRequest
from ai_engine.schemas.pipeline import PipelineResult

logger = logging.getLogger(__name__)


class DocumentProcessingPipeline:
    """Orchestrates Ingestion -> Classification -> Extraction -> Provenance Validation.

    Produces verification-ready outputs marked PENDING_REVIEW. Never marks records
    as verified, never persists to a database, and never generates summaries from
    unverified extractions.
    """

    def __init__(
        self,
        ingestion_engine: Optional[DocumentIngestionEngine] = None,
        provider: Optional[AIProvider] = None,
        provider_config: Optional[AIProviderConfig] = None,
    ):
        self.ingestion_engine = ingestion_engine or DocumentIngestionEngine()
        self.provider = provider or get_ai_provider(provider_config)

    async def process_document(
        self,
        request: IngestionRequest,
        document_id: Optional[str] = None,
    ) -> PipelineResult:
        """Process a validated IngestionRequest through the full AI pipeline."""
        return await self.process_bytes(
            file_bytes=request.file_bytes,
            original_filename=request.original_filename,
            mime_type=request.mime_type,
            document_id=document_id,
        )

    async def process_bytes(
        self,
        file_bytes: bytes,
        original_filename: str = "document",
        mime_type: Optional[str] = None,
        document_id: Optional[str] = None,
    ) -> PipelineResult:
        """Process raw document bytes asynchronously without filesystem or DB coupling."""
        # 1. Ingestion (validation, magic bytes, PyMuPDF/OCR via asyncio.to_thread)
        ingestion_result = await self.ingestion_engine.ingest_bytes(
            file_bytes=file_bytes,
            original_filename=original_filename,
            mime_type=mime_type,
        )
        if not ingestion_result.success:
            return PipelineResult(
                success=False,
                verification_status=VerificationStatus.PENDING_REVIEW,
                is_clinically_verified=False,
                ingestion=ingestion_result,
                stage_failed="ingestion",
                error_type=ingestion_result.error_type,
                error_message=ingestion_result.error_message,
            )

        # 2. Format extracted pages with explicit page markers to preserve provenance
        page_chunks = [
            f"[Page {page.page_number}]\n{page.text}"
            for page in ingestion_result.pages
            if page.text and page.text.strip()
        ]
        combined_text = "\n\n".join(page_chunks)

        if not combined_text.strip():
            return PipelineResult(
                success=False,
                verification_status=VerificationStatus.PENDING_REVIEW,
                is_clinically_verified=False,
                ingestion=ingestion_result,
                stage_failed="ingestion",
                error_type="EMPTY_EXTRACTED_TEXT",
                error_message="No readable text was extracted from the document.",
            )

        # 3. Document Classification
        try:
            raw_classification = await self.provider.classify_document(combined_text)
            classification = ClassificationResult.model_validate(raw_classification)
        except AIProviderError as e:
            logger.warning("Pipeline classification failed (%s)", e.error_type)
            return PipelineResult(
                success=False,
                verification_status=VerificationStatus.PENDING_REVIEW,
                is_clinically_verified=False,
                ingestion=ingestion_result,
                stage_failed="classification",
                error_type=e.error_type,
                error_message=e.message,
            )
        except (ValidationError, ValueError) as e:
            logger.warning("Pipeline classification validation failed (%s)", type(e).__name__)
            return PipelineResult(
                success=False,
                verification_status=VerificationStatus.PENDING_REVIEW,
                is_clinically_verified=False,
                ingestion=ingestion_result,
                stage_failed="classification",
                error_type="CLASSIFICATION_VALIDATION_ERROR",
                error_message="Classification output failed schema validation.",
            )

        # 4. Structured Information Extraction
        try:
            raw_extraction = await self.provider.extract_information(
                combined_text,
                classification.document_type.value,
            )
            extraction = ExtractionResult.model_validate(raw_extraction)
        except AIProviderError as e:
            logger.warning("Pipeline extraction failed (%s)", e.error_type)
            return PipelineResult(
                success=False,
                verification_status=VerificationStatus.PENDING_REVIEW,
                is_clinically_verified=False,
                ingestion=ingestion_result,
                classification=classification,
                stage_failed="extraction",
                error_type=e.error_type,
                error_message=e.message,
            )
        except (ValidationError, ValueError) as e:
            logger.warning("Pipeline extraction validation failed (%s)", type(e).__name__)
            return PipelineResult(
                success=False,
                verification_status=VerificationStatus.PENDING_REVIEW,
                is_clinically_verified=False,
                ingestion=ingestion_result,
                classification=classification,
                stage_failed="extraction",
                error_type="EXTRACTION_VALIDATION_ERROR",
                error_message="Extraction output failed schema validation.",
            )

        # 5. Provenance Validation against actual ingested pages
        validated_extraction = validate_extraction_provenance(
            extraction=extraction,
            pages=ingestion_result.pages,
            document_id=document_id,
        )

        # 6. Extract Insurance Profile if document is classified as insurance_doc
        insurance_profile = None
        if classification.document_type == DocumentType.INSURANCE_DOC:
            try:
                insurance_engine = InsuranceIntelligenceEngine(
                    ingestion_engine=self.ingestion_engine,
                    provider=self.provider,
                )
                insurance_res = await insurance_engine.extract_from_ingestion(
                    ingestion_result=ingestion_result,
                    document_id=document_id or original_filename,
                )
                if insurance_res.success:
                    insurance_profile = insurance_res.policy_profile
            except Exception as e:
                logger.warning("Pipeline insurance extraction failed: %s", type(e).__name__)

        # 7. Return verification-ready result (always PENDING_REVIEW)
        return PipelineResult(
            success=True,
            verification_status=VerificationStatus.PENDING_REVIEW,
            is_clinically_verified=False,
            ingestion=ingestion_result,
            classification=classification,
            extraction=validated_extraction,
            insurance_extraction=insurance_profile,
        )
