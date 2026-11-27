"""Automated tests for BridgeCare Medical Document Ingestion Engine."""

import hashlib
import io
from unittest.mock import patch

import fitz
from PIL import Image
from pydantic import ValidationError
import pytest
import pytesseract

from ai_engine.ingestion.config import IngestionConfig
from ai_engine.ingestion.engine import DocumentIngestionEngine
from ai_engine.ingestion.ocr import (
    apply_tesseract_cmd,
    extract_ocr_confidence,
    get_tesseract_version,
    run_ocr,
)
from ai_engine.schemas.common import (
    ConfidenceCategory,
    ConfidenceScore,
    ExtractionMethod,
)
from ai_engine.schemas.ingestion import IngestionRequest, IngestionResult


# =============================================================================
# Synthetic Fixture Generators
# =============================================================================


def make_digital_pdf(pages_text: list[str]) -> bytes:
    """Generate a valid synthetic PDF with digital text."""
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 72), text, fontsize=12)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def make_scanned_pdf(num_pages: int = 1) -> bytes:
    """Generate a synthetic scanned PDF containing only embedded images and no digital text."""
    doc = fitz.open()
    for _ in range(num_pages):
        page = doc.new_page(width=595, height=842)
        # Generate a synthetic image and insert it
        img = Image.new("RGB", (300, 150), color=(240, 240, 240))
        bio = io.BytesIO()
        img.save(bio, format="PNG")
        page.insert_image(page.rect, stream=bio.getvalue())
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def make_mixed_pdf() -> bytes:
    """Generate a synthetic 2-page PDF: Page 1 has digital text, Page 2 is an image (scanned)."""
    doc = fitz.open()
    # Page 1: Digital text
    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((50, 72), "Laboratory Test Report: Hemoglobin 14.5 g/dL Normal Range 13.0-17.0", fontsize=12)
    # Page 2: Image only (no digital text)
    page2 = doc.new_page(width=595, height=842)
    img = Image.new("RGB", (300, 150), color=(250, 250, 250))
    bio = io.BytesIO()
    img.save(bio, format="PNG")
    page2.insert_image(page2.rect, stream=bio.getvalue())
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def make_encrypted_pdf() -> bytes:
    """Generate a synthetic encrypted PDF."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 72), "Confidential Medical Record", fontsize=12)
    pdf_bytes = doc.tobytes(
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="secret_owner",
        user_pw="secret_user",
    )
    doc.close()
    return pdf_bytes


def make_synthetic_image(fmt: str = "PNG", size: tuple[int, int] = (200, 100)) -> bytes:
    """Generate a synthetic PNG or JPEG image byte stream."""
    img = Image.new("RGB", size, color=(255, 255, 255))
    bio = io.BytesIO()
    img.save(bio, format=fmt)
    return bio.getvalue()


MOCK_OCR_DATA = {
    "text": ["", "Hemoglobin", "", "14.5", "g/dL"],
    "conf": [-1, "95", -1, "92", "88"],
}
MOCK_OCR_TEXT = "Hemoglobin 14.5 g/dL"


# =============================================================================
# Automated Test Cases
# =============================================================================


@pytest.mark.asyncio
async def test_valid_digital_pdf():
    """Test ingestion of a valid digital PDF using PyMuPDF text extraction."""
    engine = DocumentIngestionEngine()
    pdf_bytes = make_digital_pdf(["Complete Blood Count\nHemoglobin: 14.2 g/dL\nPlatelets: 250,000 /uL"])

    req = IngestionRequest(
        file_bytes=pdf_bytes,
        original_filename="cbc_report.pdf",
        mime_type="application/pdf",
    )
    result = await engine.ingest(req)

    assert result.success is True
    assert result.error_type is None
    assert result.metadata is not None
    assert result.metadata.original_filename == "cbc_report.pdf"
    assert result.metadata.mime_type == "application/pdf"
    assert result.metadata.page_count == 1
    assert result.metadata.extraction_method == ExtractionMethod.DIGITAL
    assert len(result.pages) == 1
    assert result.pages[0].page_number == 1
    assert result.pages[0].extraction_method == ExtractionMethod.DIGITAL
    assert "Hemoglobin: 14.2 g/dL" in result.pages[0].text
    assert result.pages[0].ocr_confidence is None
    assert result.pages[0].source_reference is not None


@pytest.mark.asyncio
async def test_valid_scanned_pdf_uses_ocr():
    """Test ingestion of a scanned PDF falling back to Tesseract OCR when digital text is unavailable."""
    engine = DocumentIngestionEngine()
    pdf_bytes = make_scanned_pdf(num_pages=1)

    with patch("pytesseract.image_to_data", return_value=MOCK_OCR_DATA), \
         patch("pytesseract.image_to_string", return_value=MOCK_OCR_TEXT):
        result = await engine.ingest_bytes(pdf_bytes, original_filename="scanned_lab.pdf")

    assert result.success is True
    assert result.metadata is not None
    assert result.metadata.page_count == 1
    assert result.metadata.extraction_method == ExtractionMethod.OCR
    assert len(result.pages) == 1
    assert result.pages[0].page_number == 1
    assert result.pages[0].extraction_method == ExtractionMethod.OCR
    assert result.pages[0].text == MOCK_OCR_TEXT
    assert result.pages[0].ocr_confidence is not None
    assert result.pages[0].ocr_confidence.score == pytest.approx(0.9167, abs=0.01)
    assert result.pages[0].ocr_confidence.category == ConfidenceCategory.HIGH


@pytest.mark.asyncio
async def test_valid_png_image():
    """Test ingestion of a valid PNG image document."""
    engine = DocumentIngestionEngine()
    png_bytes = make_synthetic_image(fmt="PNG")

    with patch("pytesseract.image_to_data", return_value=MOCK_OCR_DATA), \
         patch("pytesseract.image_to_string", return_value=MOCK_OCR_TEXT):
        req = IngestionRequest(
            file_bytes=png_bytes,
            original_filename="prescription.png",
            mime_type="image/png",
        )
        result = await engine.ingest(req)

    assert result.success is True
    assert result.metadata is not None
    assert result.metadata.original_filename == "prescription.png"
    assert result.metadata.mime_type == "image/png"
    assert result.metadata.page_count == 1
    assert result.metadata.extraction_method == ExtractionMethod.OCR
    assert len(result.pages) == 1
    assert result.pages[0].page_number == 1
    assert result.pages[0].extraction_method == ExtractionMethod.OCR
    assert result.pages[0].text == MOCK_OCR_TEXT
    assert result.pages[0].ocr_confidence is not None


@pytest.mark.asyncio
async def test_valid_jpeg_image():
    """Test ingestion of a valid JPEG image document."""
    engine = DocumentIngestionEngine()
    jpeg_bytes = make_synthetic_image(fmt="JPEG")

    with patch("pytesseract.image_to_data", return_value=MOCK_OCR_DATA), \
         patch("pytesseract.image_to_string", return_value=MOCK_OCR_TEXT):
        result = await engine.ingest_bytes(jpeg_bytes, original_filename="rx.jpg")

    assert result.success is True
    assert result.metadata is not None
    assert result.metadata.mime_type == "image/jpeg"
    assert result.metadata.page_count == 1
    assert result.metadata.extraction_method == ExtractionMethod.OCR
    assert len(result.pages) == 1
    assert result.pages[0].page_number == 1
    assert result.pages[0].text == MOCK_OCR_TEXT


@pytest.mark.asyncio
async def test_invalid_file_signature():
    """Test rejection of file with spoofed extension and invalid magic bytes."""
    engine = DocumentIngestionEngine()
    # Spoofed PDF file with plain text binary content
    fake_bytes = b"Hello, this is just plain text content masquerading as a PDF."

    result = await engine.ingest_bytes(fake_bytes, original_filename="fake.pdf")

    assert result.success is False
    assert result.error_type == "INVALID_FILE_SIGNATURE"
    assert "File signature does not match" in result.error_message
    assert result.metadata is None
    assert result.pages == []


@pytest.mark.asyncio
async def test_unsupported_file_type():
    """Test rejection of unsupported file types like GIF, BMP, or ZIP."""
    engine = DocumentIngestionEngine()
    # GIF89a header
    gif_bytes = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"

    result = await engine.ingest_bytes(gif_bytes, original_filename="animation.gif")

    assert result.success is False
    assert result.error_type == "INVALID_FILE_SIGNATURE"
    assert result.metadata is None


@pytest.mark.asyncio
async def test_empty_file_handling():
    """Test rejection of empty file (0 bytes)."""
    engine = DocumentIngestionEngine()

    # IngestionRequest schema level rejection
    with pytest.raises(ValidationError):
        IngestionRequest(file_bytes=b"", original_filename="empty.pdf", mime_type="application/pdf")

    # Engine level rejection
    result = await engine.ingest_bytes(b"", original_filename="empty.pdf")
    assert result.success is False
    assert result.error_type == "EMPTY_FILE"
    assert "empty" in result.error_message.lower()


@pytest.mark.asyncio
async def test_oversized_file_rejection():
    """Test enforcement of configurable maximum file size limit."""
    # Configure tiny limit of 500 bytes for testing
    cfg = IngestionConfig(max_file_size_bytes=500)
    engine = DocumentIngestionEngine(config=cfg)

    pdf_bytes = make_digital_pdf(["Medical record content exceeding limit"])
    assert len(pdf_bytes) > 500

    result = await engine.ingest_bytes(pdf_bytes, original_filename="large.pdf")
    assert result.success is False
    assert result.error_type == "FILE_TOO_LARGE"
    assert "exceeds the maximum allowed limit" in result.error_message


@pytest.mark.asyncio
async def test_corrupt_pdf_handling():
    """Test safe handling of corrupt and malformed PDF files without crashes."""
    engine = DocumentIngestionEngine()
    # Starts with %PDF- header but contains corrupt junk
    corrupt_bytes = b"%PDF-1.4\n%Malformed and truncated body\x00\x01\x02\xff"

    result = await engine.ingest_bytes(corrupt_bytes, original_filename="broken.pdf")
    assert result.success is False
    assert result.error_type == "CORRUPT_DOCUMENT"
    assert "Failed to parse PDF" in result.error_message


@pytest.mark.asyncio
async def test_encrypted_pdf_handling():
    """Test safe rejection of encrypted or password-protected PDFs."""
    engine = DocumentIngestionEngine()
    encrypted_bytes = make_encrypted_pdf()

    result = await engine.ingest_bytes(encrypted_bytes, original_filename="protected.pdf")
    assert result.success is False
    assert result.error_type == "ENCRYPTED_DOCUMENT"
    assert "Encrypted or password-protected" in result.error_message


@pytest.mark.asyncio
async def test_multi_page_pdf():
    """Test multi-page PDF ingestion with page numbers preserved accurately."""
    engine = DocumentIngestionEngine()
    pages_text = [
        "Page 1: Patient Admission and Demographics Clinical Summary",
        "Page 2: Vital Signs and Diagnostic Assessment Details",
        "Page 3: Discharge Medications and Follow-up Instructions",
    ]
    pdf_bytes = make_digital_pdf(pages_text)

    result = await engine.ingest_bytes(pdf_bytes, original_filename="discharge.pdf")

    assert result.success is True
    assert result.metadata.page_count == 3
    assert len(result.pages) == 3
    for idx, expected_text in enumerate(pages_text, start=1):
        page = result.pages[idx - 1]
        assert page.page_number == idx
        assert expected_text in page.text
        assert page.extraction_method == ExtractionMethod.DIGITAL


@pytest.mark.asyncio
async def test_per_page_extraction_method_and_mixed_metadata():
    """Test mixed document containing both digital text and OCR pages."""
    engine = DocumentIngestionEngine()
    mixed_bytes = make_mixed_pdf()

    with patch("pytesseract.image_to_data", return_value=MOCK_OCR_DATA), \
         patch("pytesseract.image_to_string", return_value="Scanned handwritten notes"):
        result = await engine.ingest_bytes(mixed_bytes, original_filename="mixed.pdf")

    assert result.success is True
    assert result.metadata.page_count == 2
    # Document overall should accurately be marked MIXED
    assert result.metadata.extraction_method == ExtractionMethod.MIXED

    # Page 1 must be DIGITAL
    assert result.pages[0].page_number == 1
    assert result.pages[0].extraction_method == ExtractionMethod.DIGITAL
    assert result.pages[0].ocr_confidence is None
    assert "Laboratory Test Report" in result.pages[0].text

    # Page 2 must be OCR
    assert result.pages[1].page_number == 2
    assert result.pages[1].extraction_method == ExtractionMethod.OCR
    assert result.pages[1].ocr_confidence is not None
    assert "Scanned handwritten notes" in result.pages[1].text


@pytest.mark.asyncio
async def test_sha256_metadata_calculation():
    """Test accurate SHA-256 checksum generation in document metadata."""
    engine = DocumentIngestionEngine()
    pdf_bytes = make_digital_pdf(["Test document content for cryptographic hash check."])
    expected_hash = hashlib.sha256(pdf_bytes).hexdigest()

    result = await engine.ingest_bytes(pdf_bytes, original_filename="hashed.pdf")

    assert result.success is True
    assert result.metadata.sha256 == expected_hash
    assert len(result.metadata.sha256) == 64
    assert result.metadata.file_size_bytes == len(pdf_bytes)


@pytest.mark.asyncio
async def test_ocr_failure_handling_preserves_pages():
    """Test that OCR failure does not silently drop pages and reports the issue cleanly."""
    engine = DocumentIngestionEngine()
    pdf_bytes = make_scanned_pdf(num_pages=1)

    # Mock Tesseract to simulate TesseractNotFoundError (executable missing)
    with patch("pytesseract.image_to_data", side_effect=pytesseract.TesseractNotFoundError()):
        result = await engine.ingest_bytes(pdf_bytes, original_filename="unreadable.pdf")

    # Ingestion should report the extraction issue and preserve page structure
    assert len(result.pages) == 1
    assert result.pages[0].page_number == 1
    assert result.pages[0].extraction_method == ExtractionMethod.OCR
    assert result.pages[0].error_message is not None
    assert "Tesseract OCR executable not installed" in result.pages[0].error_message
    assert result.pages[0].ocr_confidence.category == ConfidenceCategory.UNCERTAIN


@pytest.mark.asyncio
async def test_image_dimension_limits():
    """Test that images exceeding dimension limits are rejected safely."""
    cfg = IngestionConfig(max_image_width=500, max_image_height=500)
    engine = DocumentIngestionEngine(config=cfg)

    # Generate an 800x400 image (width 800 > max 500)
    img_bytes = make_synthetic_image(fmt="PNG", size=(800, 400))
    result = await engine.ingest_bytes(img_bytes, original_filename="large_img.png")

    assert result.success is False
    assert result.error_type == "IMAGE_DIMENSIONS_EXCEEDED"
    assert "exceed allowed maximums" in result.error_message


def test_ocr_confidence_categories():
    """Unit test for OCR confidence categorization logic."""
    high_data = {"text": ["Blood", "Test"], "conf": ["90", "85"]}
    score_high = extract_ocr_confidence(high_data)
    assert score_high.category == ConfidenceCategory.HIGH
    assert score_high.score == pytest.approx(0.875)

    med_data = {"text": ["Lab"], "conf": ["65"]}
    score_med = extract_ocr_confidence(med_data)
    assert score_med.category == ConfidenceCategory.MEDIUM
    assert score_med.score == pytest.approx(0.65)

    low_data = {"text": ["Blurry"], "conf": ["40"]}
    score_low = extract_ocr_confidence(low_data)
    assert score_low.category == ConfidenceCategory.LOW
    assert score_low.score == pytest.approx(0.40)

    empty_data = {"text": ["", "   "], "conf": [-1, -1]}
    score_empty = extract_ocr_confidence(empty_data)
    assert score_empty.category == ConfidenceCategory.UNCERTAIN
    assert score_empty.score is None


def test_custom_tesseract_path_propagated(monkeypatch):
    """Test that custom Tesseract executable paths from config or environment are propagated."""
    custom_path = "/usr/local/custom/bin/tesseract_ocr"

    # 1. Propagated via apply_tesseract_cmd directly
    applied = apply_tesseract_cmd(custom_path)
    assert applied == custom_path
    assert pytesseract.pytesseract.tesseract_cmd == custom_path

    # 2. Propagated via IngestionConfig instantiation
    cfg = IngestionConfig(tesseract_cmd="/custom/path/from_config")
    assert cfg.tesseract_cmd == "/custom/path/from_config"
    assert pytesseract.pytesseract.tesseract_cmd == "/custom/path/from_config"

    # 3. Propagated via BRIDGECARE_INGESTION_TESSERACT_CMD environment variable
    monkeypatch.setenv("BRIDGECARE_INGESTION_TESSERACT_CMD", "/env/tesseract/bin")
    cfg_env = IngestionConfig()
    assert cfg_env.tesseract_cmd == "/env/tesseract/bin"
    assert pytesseract.pytesseract.tesseract_cmd == "/env/tesseract/bin"

    # 4. Propagated via DocumentIngestionEngine initialization
    engine = DocumentIngestionEngine(config=IngestionConfig(tesseract_cmd="/engine/tesseract"))
    assert pytesseract.pytesseract.tesseract_cmd == "/engine/tesseract"


def test_default_tesseract_executable_setting(monkeypatch):
    """Test that default executable setting falls back sensibly without breaking."""
    monkeypatch.delenv("BRIDGECARE_INGESTION_TESSERACT_CMD", raising=False)
    monkeypatch.delenv("TESSERACT_CMD", raising=False)

    cfg = IngestionConfig()
    assert cfg.tesseract_cmd is None

    # Reset with None
    active = apply_tesseract_cmd(None)
    assert active in ("tesseract", pytesseract.pytesseract.tesseract_cmd)


@pytest.mark.asyncio
async def test_missing_or_invalid_executable_path_produces_safe_errors():
    """Test that non-existent or invalid executable paths produce safe, structured errors."""
    invalid_path = "/non/existent/bogus/path/to/tesseract_executable_xyz"
    cfg = IngestionConfig(tesseract_cmd=invalid_path)

    # 1. Version check raises TesseractNotFoundError safely
    with pytest.raises(pytesseract.TesseractNotFoundError):
        get_tesseract_version(cfg)

    # 2. run_ocr returns safe structured OCRResult without throwing unhandled exceptions
    img = Image.new("RGB", (100, 50), color=(255, 255, 255))
    ocr_result = run_ocr(img, cfg)
    assert ocr_result.success is False
    assert ocr_result.error_message is not None
    assert "Tesseract OCR executable not installed" in ocr_result.error_message
    assert ocr_result.confidence.category == ConfidenceCategory.UNCERTAIN

    # 3. Engine document ingestion returns structured failure without crashing
    engine = DocumentIngestionEngine(config=cfg)
    img_bytes = make_synthetic_image(fmt="PNG")
    ingest_result = await engine.ingest_bytes(img_bytes, original_filename="scan.png")
    assert ingest_result.success is False
    assert ingest_result.error_type == "EXTRACTION_FAILED"
    assert len(ingest_result.pages) == 1
    assert "Tesseract OCR executable not installed" in ingest_result.pages[0].error_message
