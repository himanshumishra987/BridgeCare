"""Automated tests for Milestone 4: End-to-End AI Pipeline & Provenance Validation."""

import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import fitz
from PIL import Image
import pytest

from ai_engine.pipeline import DocumentProcessingPipeline
from ai_engine.providers import (
    AIProviderConfig,
    GeminiProvider,
    ProviderAPIError,
    ProviderResponseError,
)
from ai_engine.schemas.common import ExtractionMethod, VerificationStatus


def _make_digital_pdf(pages_text: list[str]) -> bytes:
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 72), text, fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def _make_scanned_pdf(num_pages: int = 1) -> bytes:
    doc = fitz.open()
    for _ in range(num_pages):
        page = doc.new_page(width=595, height=842)
        img = Image.new("RGB", (200, 100), color=(255, 255, 255))
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        page.insert_image(page.rect, stream=bio.getvalue())
    data = doc.tobytes()
    doc.close()
    return data


def _make_mixed_pdf() -> bytes:
    doc = fitz.open()
    p1 = doc.new_page(width=595, height=842)
    p1.insert_text((50, 72), "Synthetic Lab Report: Hemoglobin 14.1 g/dL (Ref: 12.0-16.0)", fontsize=12)
    p2 = doc.new_page(width=595, height=842)
    img = Image.new("RGB", (200, 100), color=(250, 250, 250))
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    p2.insert_image(p2.rect, stream=bio.getvalue())
    data = doc.tobytes()
    doc.close()
    return data


def _make_png_bytes() -> bytes:
    img = Image.new("RGB", (200, 100), color=(255, 255, 255))
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    return bio.getvalue()


def _make_gemini_provider_with_responses(responses: list[str | Exception]) -> GeminiProvider:
    client = MagicMock()
    side_effects = [
        r if isinstance(r, Exception) else SimpleNamespace(text=r)
        for r in responses
    ]
    client.aio.models.generate_content = AsyncMock(side_effect=side_effects)
    cfg = AIProviderConfig(
        bridgecare_ai_provider="gemini",
        gemini_api_key="synthetic-key",
        gemini_model="gemini-3.5-flash-lite",
        gemini_max_retries=0,
        gemini_retry_base_delay_seconds=0.0,
    )
    return GeminiProvider(config=cfg, client=client)


@pytest.mark.asyncio
async def test_pipeline_successful_digital_pdf_workflow():
    """Test end-to-end digital PDF pipeline sets PENDING_REVIEW and preserves provenance."""
    pdf_bytes = _make_digital_pdf(
        ["[Page 1] Synthetic Lab Report\nHemoglobin: 14.1 g/dL (Ref: 12.0-16.0)"]
    )
    classify_json = json.dumps(
        {
            "document_type": "lab_report",
            "confidence_score": 0.95,
            "confidence_category": "high",
            "uncertainty_reasons": [],
        }
    )
    extract_json = json.dumps(
        {
            "document_date": None,
            "biomarkers": [
                {
                    "name": "Hemoglobin",
                    "value": "14.1",
                    "numeric_value": 14.1,
                    "unit": "g/dL",
                    "reference_range": "12.0-16.0",
                    "source_reference": {
                        "page_number": 1,
                        "excerpt": "Hemoglobin: 14.1 g/dL",
                        "field_name": "Hemoglobin",
                    },
                }
            ],
            "medications": [],
            "clinical_events": [],
            "missing_fields": [],
            "uncertainty_flags": [],
            "overall_confidence_score": 0.94,
            "overall_confidence_category": "high",
        }
    )
    provider = _make_gemini_provider_with_responses([classify_json, extract_json])
    pipeline = DocumentProcessingPipeline(provider=provider)

    res = await pipeline.process_bytes(
        pdf_bytes,
        original_filename="lab.pdf",
        document_id="doc-101",
    )

    assert res.success is True
    assert res.verification_status == VerificationStatus.PENDING_REVIEW
    assert res.is_clinically_verified is False
    assert res.ingestion.metadata.extraction_method == ExtractionMethod.DIGITAL
    assert res.classification.document_type.value == "lab_report"
    assert res.extraction.biomarkers[0].source_reference is not None
    assert res.extraction.biomarkers[0].source_reference.document_id == "doc-101"
    assert res.extraction.biomarkers[0].source_reference.page_number == 1


@pytest.mark.asyncio
async def test_pipeline_successful_scanned_pdf_workflow():
    """Test end-to-end scanned PDF pipeline using OCR fallback."""
    pdf_bytes = _make_scanned_pdf(1)
    classify_json = json.dumps(
        {"document_type": "prescription", "confidence_score": 0.9, "confidence_category": "high"}
    )
    extract_json = json.dumps(
        {
            "medications": [
                {
                    "brand_name": "ExampleMed",
                    "strength": "500 mg",
                    "source_reference": {"page_number": 1, "excerpt": "Rx: ExampleMed 500 mg daily"},
                }
            ],
            "overall_confidence_score": 0.88,
            "overall_confidence_category": "high",
        }
    )
    provider = _make_gemini_provider_with_responses([classify_json, extract_json])
    pipeline = DocumentProcessingPipeline(provider=provider)

    ocr_data = {"text": ["Rx:", "ExampleMed", "500", "mg", "daily"], "conf": ["92", "90", "91", "89", "90"]}
    with patch("pytesseract.image_to_data", return_value=ocr_data), \
         patch("pytesseract.image_to_string", return_value="Rx: ExampleMed 500 mg daily"):
        res = await pipeline.process_bytes(pdf_bytes, original_filename="scanned_rx.pdf")

    assert res.success is True
    assert res.verification_status == VerificationStatus.PENDING_REVIEW
    assert res.ingestion.metadata.extraction_method == ExtractionMethod.OCR
    assert res.classification.document_type.value == "prescription"
    assert res.extraction.medications[0].brand_name == "ExampleMed"
    assert res.extraction.medications[0].source_reference is not None


@pytest.mark.asyncio
async def test_pipeline_image_ingestion_workflow():
    """Test end-to-end PNG image pipeline."""
    png_bytes = _make_png_bytes()
    classify_json = json.dumps(
        {"document_type": "clinical_note", "confidence_score": 0.85, "confidence_category": "high"}
    )
    extract_json = json.dumps(
        {
            "clinical_events": [
                {
                    "event_type": "symptom",
                    "description": "Mild headache reported.",
                    "source_reference": {"page_number": 1, "excerpt": "Mild headache reported"},
                }
            ],
            "overall_confidence_score": 0.85,
            "overall_confidence_category": "high",
        }
    )
    provider = _make_gemini_provider_with_responses([classify_json, extract_json])
    pipeline = DocumentProcessingPipeline(provider=provider)

    ocr_data = {"text": ["Mild", "headache", "reported", "today"], "conf": ["90", "90", "90", "90"]}
    with patch("pytesseract.image_to_data", return_value=ocr_data), \
         patch("pytesseract.image_to_string", return_value="Mild headache reported today"):
        res = await pipeline.process_bytes(png_bytes, original_filename="note.png")

    assert res.success is True
    assert res.ingestion.metadata.mime_type == "image/png"
    assert res.classification.document_type.value == "clinical_note"
    assert res.extraction.clinical_events[0].source_reference.page_number == 1


@pytest.mark.asyncio
async def test_pipeline_mixed_digital_and_ocr_multipage_provenance():
    """Test mixed digital/OCR multi-page PDF preserves per-page methods and validates multi-page references."""
    mixed_pdf = _make_mixed_pdf()
    classify_json = json.dumps(
        {"document_type": "lab_report", "confidence_score": 0.9, "confidence_category": "high"}
    )
    extract_json = json.dumps(
        {
            "biomarkers": [
                {
                    "name": "Hemoglobin",
                    "value": "14.1",
                    "unit": "g/dL",
                    "source_reference": {"page_number": 1, "excerpt": "Hemoglobin   14.1   g/dL"},
                },
                {
                    "name": "Glucose",
                    "value": "98",
                    "unit": "mg/dL",
                    "source_reference": {"page_number": 2, "excerpt": "Glucose 98 mg/dL"},
                },
                {
                    "name": "HallucinatedMarker",
                    "value": "5.0",
                    "source_reference": {"page_number": 99, "excerpt": "Nonexistent page 99"},
                },
                {
                    "name": "MismatchedExcerpt",
                    "value": "1.0",
                    "source_reference": {"page_number": 1, "excerpt": "Text not present on page 1"},
                },
            ],
            "overall_confidence_score": 0.85,
            "overall_confidence_category": "medium",
        }
    )
    provider = _make_gemini_provider_with_responses([classify_json, extract_json])
    pipeline = DocumentProcessingPipeline(provider=provider)

    ocr_data = {"text": ["Glucose", "98", "mg/dL"], "conf": ["90", "90", "90"]}
    with patch("pytesseract.image_to_data", return_value=ocr_data), \
         patch("pytesseract.image_to_string", return_value="Glucose 98 mg/dL"):
        res = await pipeline.process_bytes(mixed_pdf, original_filename="mixed.pdf")

    assert res.success is True
    assert res.ingestion.metadata.extraction_method == ExtractionMethod.MIXED
    assert res.verification_status == VerificationStatus.PENDING_REVIEW

    # Page 1 and Page 2 valid references preserved (whitespace normalized)
    assert res.extraction.biomarkers[0].source_reference.page_number == 1
    assert res.extraction.biomarkers[1].source_reference.page_number == 2
    # Invalid page 99 and mismatched excerpt stripped and flagged as uncertain
    assert res.extraction.biomarkers[2].source_reference is None
    assert res.extraction.biomarkers[3].source_reference is None
    assert len(res.extraction.uncertainty_flags) == 2


@pytest.mark.asyncio
async def test_pipeline_invalid_document_fails_at_ingestion():
    """Test invalid file signature stops at ingestion without calling AI provider."""
    provider = _make_gemini_provider_with_responses([])
    pipeline = DocumentProcessingPipeline(provider=provider)

    res = await pipeline.process_bytes(b"NOT_A_VALID_PDF", original_filename="bad.pdf")

    assert res.success is False
    assert res.stage_failed == "ingestion"
    assert res.error_type == "INVALID_FILE_SIGNATURE"
    assert res.classification is None
    assert res.extraction is None


@pytest.mark.asyncio
async def test_pipeline_classification_failure_returns_structured_error():
    """Test classification failure stops pipeline cleanly without mock fallback."""
    pdf_bytes = _make_digital_pdf(["Synthetic Lab Report: Hemoglobin 14.0 g/dL normal."])
    provider = _make_gemini_provider_with_responses([ProviderResponseError("Malformed JSON")])
    pipeline = DocumentProcessingPipeline(provider=provider)

    res = await pipeline.process_bytes(pdf_bytes, original_filename="lab.pdf")

    assert res.success is False
    assert res.stage_failed == "classification"
    assert res.error_type == "PROVIDER_RESPONSE_ERROR"
    assert res.ingestion.success is True
    assert res.extraction is None


@pytest.mark.asyncio
async def test_pipeline_extraction_failure_returns_structured_error():
    """Test extraction failure preserves classification and returns structured error."""
    pdf_bytes = _make_digital_pdf(["Synthetic Lab Report: Hemoglobin 14.0 g/dL normal."])
    classify_json = json.dumps(
        {"document_type": "lab_report", "confidence_score": 0.9, "confidence_category": "high"}
    )
    provider = _make_gemini_provider_with_responses(
        [classify_json, ProviderAPIError("API failure", status_code=500)]
    )
    pipeline = DocumentProcessingPipeline(provider=provider)

    res = await pipeline.process_bytes(pdf_bytes, original_filename="lab.pdf")

    assert res.success is False
    assert res.stage_failed == "extraction"
    assert res.error_type == "PROVIDER_API_ERROR"
    assert res.classification.document_type.value == "lab_report"
    assert res.extraction is None
