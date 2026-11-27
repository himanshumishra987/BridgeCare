"""File validation and security checks for document ingestion."""

from dataclasses import dataclass
import hashlib
from typing import Optional

from ai_engine.ingestion.config import IngestionConfig

# Recognized magic byte file signatures
PDF_MAGIC = b"%PDF-"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"

SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
}


@dataclass(frozen=True)
class FileValidationResult:
    """Result of file signature and size validation."""

    is_valid: bool
    detected_mime_type: Optional[str] = None
    sha256: Optional[str] = None
    file_size_bytes: int = 0
    error_type: Optional[str] = None
    error_message: Optional[str] = None


def detect_file_mime_type(file_bytes: bytes) -> Optional[str]:
    """Detect MIME type from file signature magic bytes.

    Validates actual file bytes rather than filename extensions or user declarations.
    """
    if file_bytes.startswith(PDF_MAGIC):
        return "application/pdf"
    if file_bytes.startswith(PNG_MAGIC):
        return "image/png"
    if file_bytes.startswith(JPEG_MAGIC):
        return "image/jpeg"
    return None


def calculate_sha256(file_bytes: bytes) -> str:
    """Calculate SHA-256 checksum for given file bytes."""
    return hashlib.sha256(file_bytes).hexdigest()


def validate_file(file_bytes: bytes, config: Optional[IngestionConfig] = None) -> FileValidationResult:
    """Validate file bytes against security policies, size limits, and signature checks."""
    cfg = config or IngestionConfig()
    size = len(file_bytes)

    if size == 0:
        return FileValidationResult(
            is_valid=False,
            file_size_bytes=0,
            error_type="EMPTY_FILE",
            error_message="Uploaded document is empty (0 bytes).",
        )

    if size > cfg.max_file_size_bytes:
        return FileValidationResult(
            is_valid=False,
            file_size_bytes=size,
            error_type="FILE_TOO_LARGE",
            error_message=(
                f"File size ({size} bytes) exceeds the maximum allowed limit "
                f"of {cfg.max_file_size_bytes} bytes."
            ),
        )

    mime_type = detect_file_mime_type(file_bytes)
    if mime_type is None:
        return FileValidationResult(
            is_valid=False,
            file_size_bytes=size,
            error_type="INVALID_FILE_SIGNATURE",
            error_message=(
                "File signature does not match any supported format. "
                "Supported formats are PDF (%PDF-), PNG, and JPEG."
            ),
        )

    sha256_hash = calculate_sha256(file_bytes)
    return FileValidationResult(
        is_valid=True,
        detected_mime_type=mime_type,
        sha256=sha256_hash,
        file_size_bytes=size,
    )
