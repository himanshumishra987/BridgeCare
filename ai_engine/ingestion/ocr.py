"""Tesseract OCR execution and confidence scoring."""

from dataclasses import dataclass
import logging
import os
import shutil
from typing import Optional

from PIL import Image
import pytesseract

from ai_engine.ingestion.config import IngestionConfig
from ai_engine.languages import validate_language_code
from ai_engine.schemas.common import ConfidenceCategory, ConfidenceScore

logger = logging.getLogger(__name__)

DEFAULT_TESSERACT_CMD = "tesseract"


def apply_tesseract_cmd(tesseract_cmd: Optional[str] = None) -> str:
    """Apply the configured Tesseract executable path to pytesseract.

    Resolution order:
    1. Explicitly provided `tesseract_cmd`.
    2. Environment variable BRIDGECARE_INGESTION_TESSERACT_CMD.
    3. Environment variable TESSERACT_CMD.
    4. Auto-discovery via shutil.which("tesseract").
    5. Fallback to default "tesseract".

    Permanently updates pytesseract.pytesseract.tesseract_cmd and returns the active path.
    """
    cmd = (
        tesseract_cmd
        or os.environ.get("BRIDGECARE_INGESTION_TESSERACT_CMD")
        or os.environ.get("TESSERACT_CMD")
    )
    if not cmd:
        cmd = shutil.which(DEFAULT_TESSERACT_CMD) or DEFAULT_TESSERACT_CMD

    pytesseract.pytesseract.tesseract_cmd = cmd
    return cmd


def get_tesseract_version(config: Optional[IngestionConfig] = None) -> str:
    """Get the installed Tesseract OCR version safely.

    Ensures the configured executable path is applied before checking version.
    Raises pytesseract.TesseractNotFoundError if the executable is missing or invalid.
    """
    if config and config.tesseract_cmd:
        apply_tesseract_cmd(config.tesseract_cmd)
    else:
        apply_tesseract_cmd()

    return str(pytesseract.get_tesseract_version())


# Automatically synchronize environment configuration upon module import
apply_tesseract_cmd()


def get_available_ocr_languages(config: Optional[IngestionConfig] = None) -> list[str]:
    """Return installed Tesseract OCR language codes (e.g. ['eng', 'osd'])."""
    apply_tesseract_cmd(config.tesseract_cmd if config else None)
    try:
        return sorted(pytesseract.get_languages(config=""))
    except Exception as e:
        logger.warning("Unable to query Tesseract OCR languages: %s", type(e).__name__)
        return []


def check_ocr_language_support(
    language_code: str,
    config: Optional[IngestionConfig] = None,
) -> tuple[bool, Optional[str]]:
    """Check whether Tesseract has the language data pack installed for a BridgeCare language code."""
    info = validate_language_code(language_code)
    available = get_available_ocr_languages(config)
    if info.tesseract_code in available:
        return True, None
    return (
        False,
        f"OCR language pack '{info.tesseract_code}' for {info.name} ({info.code}) is not installed. "
        f"Available OCR packs: {available}.",
    )


@dataclass(frozen=True)
class OCRResult:
    """Result of an OCR operation on an image."""

    success: bool
    text: str
    confidence: Optional[ConfidenceScore] = None
    error_message: Optional[str] = None


def extract_ocr_confidence(data: dict) -> ConfidenceScore:
    """Extract and calculate average word-level confidence from Tesseract data."""
    confidences: list[float] = []

    texts = data.get("text", [])
    confs = data.get("conf", [])

    for text, conf in zip(texts, confs):
        if text and text.strip():
            try:
                c = float(conf)
                # Tesseract reports -1 for non-word bounding boxes
                if c >= 0:
                    confidences.append(c)
            except (ValueError, TypeError):
                continue

    if not confidences:
        return ConfidenceScore(
            score=None,
            source="tesseract_ocr",
            category=ConfidenceCategory.UNCERTAIN,
        )

    avg_conf = sum(confidences) / len(confidences)  # 0 to 100
    score = max(0.0, min(1.0, round(avg_conf / 100.0, 4)))

    if score >= 0.80:
        category = ConfidenceCategory.HIGH
    elif score >= 0.60:
        category = ConfidenceCategory.MEDIUM
    else:
        category = ConfidenceCategory.LOW

    return ConfidenceScore(
        score=score,
        source="tesseract_ocr",
        category=category,
    )


def run_ocr(
    image: Image.Image,
    config: Optional[IngestionConfig] = None,
    ocr_lang: Optional[str] = None,
) -> OCRResult:
    """Run Tesseract OCR on a PIL Image with timeout, language checks, and error handling.

    Ensures the configured executable path is applied before every OCR operation.
    Does not log document content or sensitive patient data.
    """
    cfg = config or IngestionConfig()
    apply_tesseract_cmd(cfg.tesseract_cmd)

    tesseract_lang_arg: Optional[str] = None
    if ocr_lang is not None:
        supported, limitation_msg = check_ocr_language_support(ocr_lang, cfg)
        if not supported:
            logger.warning("Requested OCR language '%s' is not available on host.", ocr_lang)
            return OCRResult(
                success=False,
                text="",
                confidence=ConfidenceScore(
                    score=None,
                    source="tesseract_ocr",
                    category=ConfidenceCategory.UNCERTAIN,
                ),
                error_message=limitation_msg,
            )
        tesseract_lang_arg = validate_language_code(ocr_lang).tesseract_code

    try:
        lang_kwargs = {"lang": tesseract_lang_arg} if tesseract_lang_arg else {}
        # Extract word data with bounding boxes and confidences
        data = pytesseract.image_to_data(
            image,
            output_type=pytesseract.Output.DICT,
            timeout=cfg.tesseract_timeout_seconds,
            **lang_kwargs,
        )
        conf = extract_ocr_confidence(data)

        # Extract complete recognized text
        raw_text = pytesseract.image_to_string(
            image,
            timeout=cfg.tesseract_timeout_seconds,
            **lang_kwargs,
        )
        text = raw_text.strip()

        return OCRResult(
            success=True,
            text=text,
            confidence=conf,
        )

    except (pytesseract.TesseractNotFoundError, FileNotFoundError):
        logger.warning("Tesseract OCR executable not found on configured path or system PATH.")
        return OCRResult(
            success=False,
            text="",
            confidence=ConfidenceScore(
                score=None,
                source="tesseract_ocr",
                category=ConfidenceCategory.UNCERTAIN,
            ),
            error_message="Tesseract OCR executable not installed or not found on system PATH.",
        )

    except (pytesseract.TesseractError, TimeoutError) as e:
        logger.warning("OCR processing error encountered: %s", type(e).__name__)
        return OCRResult(
            success=False,
            text="",
            confidence=ConfidenceScore(
                score=None,
                source="tesseract_ocr",
                category=ConfidenceCategory.UNCERTAIN,
            ),
            error_message=f"OCR engine encountered an error: {type(e).__name__}",
        )

    except Exception as e:
        logger.warning("Unexpected error during OCR execution: %s", type(e).__name__)
        return OCRResult(
            success=False,
            text="",
            confidence=ConfidenceScore(
                score=None,
                source="tesseract_ocr",
                category=ConfidenceCategory.UNCERTAIN,
            ),
            error_message="Unexpected error during text recognition.",
        )
