"""Document ingestion engine for BridgeCare AI/ML service."""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Optional

from ai_engine.ingestion.config import IngestionConfig
from ai_engine.ingestion.image import ImageProcessingError, process_image_sync
from ai_engine.ingestion.ocr import apply_tesseract_cmd
from ai_engine.ingestion.pdf import PDFProcessingError, process_pdf_sync
from ai_engine.ingestion.validator import validate_file
from ai_engine.schemas.common import DocumentMetadata, ExtractionMethod
from ai_engine.schemas.ingestion import IngestionRequest, IngestionResult

logger = logging.getLogger(__name__)


class DocumentIngestionEngine:
    """Production document ingestion engine supporting PDF, PNG, and JPEG formats.

    Provides async-compatible non-blocking document ingestion with file signature
    verification, PDF digital text extraction, OCR fallback, and structured metadata.
    Does not log document content or personal medical information.
    """

    def __init__(self, config: Optional[IngestionConfig] = None):
        self.config = config or IngestionConfig()
        apply_tesseract_cmd(self.config.tesseract_cmd)

    async def ingest(self, request: IngestionRequest) -> IngestionResult:
        """Ingest a document from an IngestionRequest model."""
        return await self.ingest_bytes(
            file_bytes=request.file_bytes,
            original_filename=request.original_filename,
            mime_type=request.mime_type,
        )

    async def ingest_bytes(
        self,
        file_bytes: bytes,
        original_filename: str = "document",
        mime_type: Optional[str] = None,
        source_language: Optional[str] = None,
    ) -> IngestionResult:
        """Ingest document bytes asynchronously using thread pool for CPU-bound tasks."""
        # 1. Validate file safety, size, and magic byte signature
        validation = validate_file(file_bytes, self.config)
        if not validation.is_valid:
            logger.warning(
                "Ingestion validation rejected file '%s' (size: %d bytes, error: %s)",
                original_filename,
                validation.file_size_bytes,
                validation.error_type,
            )
            return IngestionResult(
                success=False,
                metadata=None,
                pages=[],
                error_type=validation.error_type,
                error_message=validation.error_message,
            )

        detected_mime = validation.detected_mime_type
        logger.info(
            "Validated document '%s': size=%d bytes, detected_mime=%s",
            original_filename,
            validation.file_size_bytes,
            detected_mime,
        )

        # 2. Extract pages using appropriate parser in thread pool
        try:
            if detected_mime == "application/pdf":
                pages, page_count = await asyncio.to_thread(
                    process_pdf_sync,
                    file_bytes,
                    self.config,
                    source_language,
                )
            elif detected_mime in ("image/png", "image/jpeg"):
                pages, page_count = await asyncio.to_thread(
                    process_image_sync,
                    file_bytes,
                    self.config,
                    source_language,
                )
            else:
                return IngestionResult(
                    success=False,
                    metadata=None,
                    pages=[],
                    error_type="UNSUPPORTED_FILE_TYPE",
                    error_message=f"Unsupported MIME type: {detected_mime}",
                )

        except (PDFProcessingError, ImageProcessingError) as e:
            logger.warning(
                "Document processing failed for '%s': %s - %s",
                original_filename,
                e.error_type,
                e.message,
            )
            return IngestionResult(
                success=False,
                metadata=None,
                pages=[],
                error_type=e.error_type,
                error_message=e.message,
            )
        except Exception as e:
            logger.exception("Unexpected error processing document '%s': %s", original_filename, type(e).__name__)
            return IngestionResult(
                success=False,
                metadata=None,
                pages=[],
                error_type="PROCESSING_ERROR",
                error_message="An unexpected error occurred while processing the document.",
            )

        # 3. Determine overall extraction method
        page_methods = {p.extraction_method for p in pages}
        if ExtractionMethod.DIGITAL in page_methods and ExtractionMethod.OCR in page_methods:
            overall_method = ExtractionMethod.MIXED
        elif ExtractionMethod.OCR in page_methods:
            overall_method = ExtractionMethod.OCR
        else:
            overall_method = ExtractionMethod.DIGITAL

        # 4. Construct document metadata
        metadata = DocumentMetadata(
            original_filename=original_filename,
            mime_type=detected_mime,
            file_size_bytes=validation.file_size_bytes,
            sha256=validation.sha256,
            page_count=page_count,
            extraction_method=overall_method,
            created_at=datetime.now(timezone.utc),
        )

        # 5. Check if all pages experienced extraction failure
        all_failed = bool(pages) and all(
            bool(p.error_message and not p.text.strip()) for p in pages
        )

        if all_failed:
            logger.warning(
                "Text extraction failed for all %d pages in '%s'",
                page_count,
                original_filename,
            )
            return IngestionResult(
                success=False,
                metadata=metadata,
                pages=pages,
                error_type="EXTRACTION_FAILED",
                error_message="Text extraction failed for all pages in document.",
            )

        logger.info(
            "Successfully ingested '%s': %d pages processed (method: %s)",
            original_filename,
            page_count,
            overall_method.value,
        )

        return IngestionResult(
            success=True,
            metadata=metadata,
            pages=pages,
            error_type=None,
            error_message=None,
        )
