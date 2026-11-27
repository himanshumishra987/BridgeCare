"""Image processing module for PNG and JPEG medical documents."""

import io
import logging
from typing import Optional, Tuple

from PIL import Image, ImageOps, UnidentifiedImageError

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


class ImageProcessingError(Exception):
    """Exception raised during image validation or processing."""

    def __init__(self, error_type: str, message: str):
        super().__init__(message)
        self.error_type = error_type
        self.message = message


def process_image_sync(
    file_bytes: bytes,
    config: IngestionConfig,
    source_language: Optional[str] = None,
) -> Tuple[list[ExtractedPage], int]:
    """Synchronous image processor for PNG and JPEG files.

    Validates dimensions and decompression bomb thresholds safely,
    then performs OCR via Tesseract. Returns page number 1.
    """
    # Enforce decompression bomb protection
    Image.MAX_IMAGE_PIXELS = config.max_image_pixels

    try:
        # Pass 1: Verify image integrity
        with io.BytesIO(file_bytes) as bio:
            with Image.open(bio) as img:
                img.verify()
    except Image.DecompressionBombError as e:
        logger.warning("Image exceeded maximum pixel threshold (decompression bomb protection).")
        raise ImageProcessingError(
            error_type="IMAGE_DIMENSIONS_EXCEEDED",
            message="Image exceeds maximum allowable pixel threshold.",
        ) from e
    except (UnidentifiedImageError, Exception) as e:
        logger.warning("Malformed or unreadable image file: %s", type(e).__name__)
        raise ImageProcessingError(
            error_type="CORRUPT_DOCUMENT",
            message="Failed to parse image file: corrupt or malformed image data.",
        ) from e

    # Pass 2: Open image to inspect dimensions and extract text
    try:
        with io.BytesIO(file_bytes) as bio:
            with Image.open(bio) as img:
                width, height = img.size
                total_pixels = width * height

                if (
                    width > config.max_image_width
                    or height > config.max_image_height
                    or total_pixels > config.max_image_pixels
                ):
                    raise ImageProcessingError(
                        error_type="IMAGE_DIMENSIONS_EXCEEDED",
                        message=(
                            f"Image dimensions ({width}x{height}, {total_pixels} pixels) "
                            f"exceed allowed maximums ({config.max_image_width}x{config.max_image_height}, "
                            f"{config.max_image_pixels} pixels)."
                        ),
                    )

                # Correct EXIF orientation and convert to RGB
                img_normalized = ImageOps.exif_transpose(img) or img
                rgb_img = img_normalized.convert("RGB")

                # Perform OCR extraction
                ocr_res = run_ocr(rgb_img, config, ocr_lang=source_language)

                page_num = 1
                text = ocr_res.text
                source_ref = (
                    SourceReference(page_number=page_num, excerpt=text[:100].strip())
                    if text.strip()
                    else None
                )

                page = ExtractedPage(
                    page_number=page_num,
                    text=text,
                    extraction_method=ExtractionMethod.OCR,
                    ocr_confidence=ocr_res.confidence,
                    source_reference=source_ref,
                    error_message=ocr_res.error_message,
                )

                return [page], 1

    except ImageProcessingError:
        raise
    except Image.DecompressionBombError as e:
        raise ImageProcessingError(
            error_type="IMAGE_DIMENSIONS_EXCEEDED",
            message="Image exceeds maximum allowable pixel threshold.",
        ) from e
    except Exception as e:
        logger.warning("Unexpected error during image processing: %s", type(e).__name__)
        raise ImageProcessingError(
            error_type="CORRUPT_DOCUMENT",
            message="Error encountered while reading image content.",
        ) from e
