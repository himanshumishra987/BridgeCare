
import pytest
from pydantic import ValidationError

from ai_engine.schemas.common import (
    ConfidenceScore,
    ConfidenceCategory,
    DocumentMetadata,
    ExtractionMethod,
    SourceReference,
)
from ai_engine.schemas.ingestion import (
    ExtractedPage,
    IngestionRequest,
)
from ai_engine.schemas.classification import (
    ClassificationResult,
    DocumentType,
)
from ai_engine.schemas.extraction import (
    ExtractionResult,
    ExtractedBiomarker,
    ExtractedMedication,
)


def test_confidence_score_accepts_valid_value():
    score = ConfidenceScore(
        score=0.95,
        source="ocr",
        category=ConfidenceCategory.HIGH,
    )
    assert score.score == 0.95


def test_confidence_score_rejects_out_of_range():
    with pytest.raises(ValidationError):
        ConfidenceScore(
            score=1.5,
            source="ocr",
            category=ConfidenceCategory.HIGH,
        )


def test_document_metadata_rejects_invalid_sha256():
    with pytest.raises(ValidationError):
        DocumentMetadata(
            original_filename="report.pdf",
            mime_type="application/pdf",
            file_size_bytes=1024,
            sha256="invalid-hash",
            page_count=1,
            extraction_method=ExtractionMethod.DIGITAL,
        )


def test_ingestion_request_rejects_empty_file():
    with pytest.raises(ValidationError):
        IngestionRequest(
            file_bytes=b"",
            original_filename="report.pdf",
            mime_type="application/pdf",
        )


def test_extracted_page_rejects_zero_page_number():
    with pytest.raises(ValidationError):
        ExtractedPage(
            page_number=0,
            text="Hemoglobin: 13.5 g/dL",
            extraction_method=ExtractionMethod.DIGITAL,
        )


def test_classification_accepts_lab_report():
    result = ClassificationResult(
        document_type=DocumentType.LAB_REPORT,
        confidence=ConfidenceScore(
            score=0.95,
            source="mock",
            category=ConfidenceCategory.HIGH,
        ),
        provider_used="mock",
        is_mock=True,
    )
    assert result.document_type == DocumentType.LAB_REPORT


def test_biomarker_preserves_original_value_and_unit():
    biomarker = ExtractedBiomarker(
        name="Hemoglobin",
        value="13.5",
        numeric_value=13.5,
        unit="g/dL",
        reference_range="12.0-16.0",
    )
    assert biomarker.value == "13.5"
    assert biomarker.unit == "g/dL"


def test_extraction_result_defaults_to_empty_lists():
    result = ExtractionResult(
        document_type=DocumentType.LAB_REPORT,
    )
    assert result.biomarkers == []
    assert result.medications == []
    assert result.clinical_events == []


def test_medication_preserves_recorded_instructions():
    medication = ExtractedMedication(
        brand_name="Example Medicine",
        strength="500 mg",
        frequency="Twice daily",
        instructions="Take after meals",
    )
    assert medication.frequency == "Twice daily"
    assert medication.instructions == "Take after meals"
