"""Secure document storage.

* Content type is decided from magic bytes, not from the client-supplied
  header, and must be in the allow-list.
* Files are written beneath ``storage_root`` using a hash-derived path so no
  client-supplied filename ever reaches the filesystem.
* Reads are containment-checked, so a tampered ``storage_key`` cannot escape
  the storage root.
* Duplicate uploads for a patient return the existing document rather than
  storing a second copy.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import (
    ConflictError,
    MalwareDetectedError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    UnsupportedMediaError,
    ValidationAppError,
)
from app.models.document import Document
from app.models.enums import DocumentScanStatus, DocumentStatus

_MAGIC_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"%PDF-", "application/pdf", ".pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
)

_UNSAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._ -]")


@dataclass(frozen=True)
class StoredDocument:
    document: Document
    created: bool


def sanitize_filename(name: str | None) -> str:
    candidate = (name or "document").replace("\\", "/").split("/")[-1]
    candidate = _UNSAFE_FILENAME_RE.sub("_", candidate).strip(" ._")
    if not candidate:
        candidate = "document"
    return candidate[:255]


def detect_content_type(head: bytes) -> tuple[str, str] | None:
    for signature, content_type, extension in _MAGIC_SIGNATURES:
        if head.startswith(signature):
            return content_type, extension
    return None


def _storage_root() -> Path:
    root = get_settings().resolved_storage_root
    root.mkdir(parents=True, exist_ok=True)
    return root


def _resolve_within_root(storage_key: str) -> Path:
    if not storage_key or ".." in storage_key or storage_key.startswith(("/", "\\")):
        raise ValidationAppError("Invalid document storage reference.")
    root = _storage_root()
    path = (root / storage_key).resolve()
    if not path.is_relative_to(root):
        raise ValidationAppError("Invalid document storage reference.")
    return path


def store_document(
    db: Session,
    *,
    patient_id: uuid.UUID,
    uploaded_by_user_id: uuid.UUID | None,
    filename: str | None,
    declared_content_type: str | None,
    data: bytes,
) -> StoredDocument:
    settings = get_settings()
    if not data:
        raise ValidationAppError("The uploaded file is empty.")
    if len(data) > settings.max_upload_bytes:
        raise PayloadTooLargeError(
            f"Documents must be {settings.max_upload_bytes // (1024 * 1024)} MB or smaller."
        )

    detected = detect_content_type(data[:16])
    if detected is None:
        raise UnsupportedMediaError("Only PDF, PNG and JPEG documents are accepted.")
    content_type, extension = detected
    if content_type not in settings.allowed_document_types:
        raise UnsupportedMediaError("This document type is not enabled for upload.")
    if (
        declared_content_type
        and declared_content_type != "application/octet-stream"
        and declared_content_type.split(";")[0].strip().lower() != content_type
    ):
        raise UnsupportedMediaError(
            "The declared file type does not match the file contents."
        )

    # IDTA gate, before anything is written or persisted: a positive or
    # inconclusive verdict must not leave a document behind that a later code
    # path could mistake for a normal upload.
    scan_status = DocumentScanStatus.PENDING
    scan_engine: str | None = None
    scan_signature_version: str | None = None
    if settings.scanner_configured:
        from app.services import idta  # local import: idta imports this module

        outcome = idta.scan_bytes(data)
        if outcome.status == DocumentScanStatus.INFECTED:
            raise MalwareDetectedError()
        if outcome.status != DocumentScanStatus.CLEAN:
            raise ServiceUnavailableError(
                "Malware scanning could not reach a verdict, so the upload was refused."
            )
        scan_status = outcome.status
        scan_engine = outcome.engine
        scan_signature_version = outcome.signature_version

    digest = hashlib.sha256(data).hexdigest()
    existing = db.scalar(
        select(Document).where(
            Document.patient_id == patient_id,
            Document.sha256 == digest,
            Document.archived_at.is_(None),
        )
    )
    if existing is not None:
        return StoredDocument(document=existing, created=False)

    storage_key = f"{patient_id}/{digest[:2]}/{digest}{extension}"
    target = _resolve_within_root(storage_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_suffix(target.suffix + ".tmp")
        with open(temporary, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)

    document = Document(
        patient_id=patient_id,
        uploaded_by_user_id=uploaded_by_user_id,
        status=DocumentStatus.UPLOADED,
        original_filename=sanitize_filename(filename),
        content_type=content_type,
        byte_size=len(data),
        sha256=digest,
        storage_key=storage_key,
        scan_status=scan_status,
        scan_engine=scan_engine,
        scan_signature_version=scan_signature_version,
    )
    if scan_status == DocumentScanStatus.CLEAN:
        from app.db.base import utcnow

        document.scanned_at = utcnow()
    db.add(document)
    db.flush()
    return StoredDocument(document=document, created=True)


def delete_document_bytes(document: Document) -> bool:
    """Purge stored bytes (quarantine); metadata is kept for the audit trail."""
    try:
        path = _resolve_within_root(document.storage_key)
    except ValidationAppError:
        return False
    if path.is_file():
        path.unlink()
        return True
    return False


def read_document_bytes(document: Document) -> bytes:
    if document.archived_at is not None:
        raise ConflictError("This document has been archived.")
    if document.scan_status == DocumentScanStatus.INFECTED or document.quarantined_at is not None:
        from app.core.errors import MalwareDetectedError

        raise MalwareDetectedError(
            "This document was quarantined after a malware scan and cannot be read."
        )
    path = _resolve_within_root(document.storage_key)
    if not path.is_file():
        raise ConflictError("The stored document is unavailable.")
    return path.read_bytes()
