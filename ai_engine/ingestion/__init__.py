"""BridgeCare Document Ingestion Module."""

from ai_engine.ingestion.config import IngestionConfig
from ai_engine.ingestion.engine import DocumentIngestionEngine
from ai_engine.ingestion.ocr import (
    OCRResult,
    apply_tesseract_cmd,
    check_ocr_language_support,
    extract_ocr_confidence,
    get_available_ocr_languages,
    get_tesseract_version,
    run_ocr,
)
from ai_engine.ingestion.validator import (
    FileValidationResult,
    calculate_sha256,
    detect_file_mime_type,
    validate_file,
)

__all__ = [
    "DocumentIngestionEngine",
    "IngestionConfig",
    "FileValidationResult",
    "OCRResult",
    "apply_tesseract_cmd",
    "calculate_sha256",
    "check_ocr_language_support",
    "detect_file_mime_type",
    "extract_ocr_confidence",
    "get_available_ocr_languages",
    "get_tesseract_version",
    "run_ocr",
    "validate_file",
]
