"""PDF processing module for digital text extraction and OCR fallback."""

import logging
from typing import Optional, Tuple

import fitz  # PyMuPDF
from PIL import Image

from ai_engine.ingestion.config import IngestionConfig
from ai_engine.ingestion.ocr import run_ocr
from ai_engine.schemas.common import (
    ConfidenceCategory,
    ConfidenceScore,
    ExtractionMethod,
    SourceReference,
)
from ai_engine.schemas.ingestion import ExtractedPage

logger = logging.getLogger(__name__)


class PDFProcessingError(Exception):
    """Exception raised during PDF parsing or validation."""

    def __init__(self, error_type: str, message: str):
        super().__init__(message)
        self.error_type = error_type
        self.message = message


def process_pdf_sync(
    file_bytes: bytes,
    config: IngestionConfig,
    source_language: Optional[str] = None,
) -> Tuple[list[ExtractedPage], int]:
    """Synchronous PDF processor using PyMuPDF and OCR fallback.

    Extracts digital text per page. If meaningful text is not available,
    renders the page to an image and runs Tesseract OCR.

    Never logs document text or sensitive medical content.
    """
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as e:
        logger.warning("Corrupt or invalid PDF file structure: %s", type(e).__name__)
        raise PDFProcessingError(
            error_type="CORRUPT_DOCUMENT",
            message="Failed to parse PDF document: corrupt or invalid file structure.",
        ) from e

    try:
        if doc.is_encrypted or doc.needs_pass:
            raise PDFProcessingError(
                error_type="ENCRYPTED_DOCUMENT",
                message="Encrypted or password-protected PDFs are not supported.",
            )

        page_count = len(doc)
        if page_count == 0:
            raise PDFProcessingError(
                error_type="CORRUPT_DOCUMENT",
                message="PDF contains no readable pages.",
            )

        if page_count > config.max_pdf_pages:
            raise PDFProcessingError(
                error_type="PAGE_COUNT_EXCEEDED",
                message=(
                    f"PDF page count ({page_count}) exceeds the maximum allowed limit "
                    f"of {config.max_pdf_pages} pages."
                ),
            )

        pages: list[ExtractedPage] = []
        zoom = config.ocr_dpi / 72.0
        render_matrix = fitz.Matrix(zoom, zoom)

        for page_index in range(page_count):
            page_num = page_index + 1
            page = doc[page_index]

            # 1. Attempt digital text extraction
            digital_text = page.get_text("text").strip()
            alnum_count = sum(1 for c in digital_text if c.isalnum())

            if alnum_count >= config.min_meaningful_chars:
                # Meaningful digital text found
                source_ref = SourceReference(
                    page_number=page_num,
                    excerpt=digital_text[:100].strip(),
                )
                pages.append(
                    ExtractedPage(
                        page_number=page_num,
                        text=digital_text,
                        extraction_method=ExtractionMethod.DIGITAL,
                        ocr_confidence=None,
                        source_reference=source_ref,
                        error_message=None,
                    )
                )
            else:
                # 2. Meaningful digital text unavailable; fall back to OCR
                try:
                    pix = page.get_pixmap(matrix=render_matrix, alpha=False)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    ocr_res = run_ocr(img, config, ocr_lang=source_language)

                    if ocr_res.success:
                        text = ocr_res.text
                        source_ref = (
                            SourceReference(page_number=page_num, excerpt=text[:100].strip())
                            if text.strip()
                            else None
                        )
                        pages.append(
                            ExtractedPage(
                                page_number=page_num,
                                text=text,
                                extraction_method=ExtractionMethod.OCR,
                                ocr_confidence=ocr_res.confidence,
                                source_reference=source_ref,
                                error_message=None,
                            )
                        )
                    else:
                        # OCR failed; do not discard page, report the issue
                        pages.append(
                            ExtractedPage(
                                page_number=page_num,
                                text=digital_text if digital_text else "",
                                extraction_method=ExtractionMethod.OCR,
                                ocr_confidence=ocr_res.confidence,
                                source_reference=None,
                                error_message=ocr_res.error_message or "OCR extraction failed for page.",
                            )
                        )
                except Exception as ex:
                    logger.warning("Error rendering/processing page %d for OCR: %s", page_num, type(ex).__name__)
                    pages.append(
                        ExtractedPage(
                            page_number=page_num,
                            text=digital_text if digital_text else "",
                            extraction_method=ExtractionMethod.OCR,
                            ocr_confidence=ConfidenceScore(
                                score=None,
                                source="tesseract_ocr",
                                category=ConfidenceCategory.UNCERTAIN,
                            ),
                            source_reference=None,
                            error_message=f"Failed to render or process page for OCR: {type(ex).__name__}",
                        )
                    )

        return pages, page_count

    finally:
        doc.close()
