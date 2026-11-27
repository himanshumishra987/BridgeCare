"""Uploaded documents and AI extraction receipts.

Documents are stored outside the web root; the database holds only metadata and
a content digest. Extractions are receipts of what the AI engine submitted, kept
separately from the human-verified records they propose.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSONColumn, Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    DocumentKind,
    DocumentScanStatus,
    DocumentSource,
    DocumentStatus,
    ExtractionStatus,
    enum_type,
)


class Document(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("patient_id", "sha256", name="uq_documents_patient_sha256"),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[DocumentKind] = mapped_column(
        enum_type(DocumentKind, 30), nullable=False, default=DocumentKind.UNKNOWN
    )
    status: Mapped[DocumentStatus] = mapped_column(
        enum_type(DocumentStatus, 20), nullable=False, default=DocumentStatus.UPLOADED, index=True
    )
    source: Mapped[DocumentSource] = mapped_column(
        enum_type(DocumentSource, 20), nullable=False, default=DocumentSource.USER_UPLOAD
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # IDTA verdict. ``PENDING``/``ERROR``/``INFECTED`` all block AI processing;
    # only an explicit ``CLEAN`` from the configured scanner permits it.
    scan_status: Mapped[DocumentScanStatus] = mapped_column(
        enum_type(DocumentScanStatus, 20),
        nullable=False,
        default=DocumentScanStatus.PENDING,
        index=True,
    )
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scan_engine: Mapped[str | None] = mapped_column(String(80))
    scan_signature_version: Mapped[str | None] = mapped_column(String(80))
    quarantined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentExtraction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Idempotent receipt of a structured extraction submitted by the AI engine."""

    __tablename__ = "document_extractions"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    extraction_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    engine_version: Mapped[str | None] = mapped_column(String(40))
    contract_version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[ExtractionStatus] = mapped_column(
        enum_type(ExtractionStatus, 20), nullable=False, default=ExtractionStatus.RECEIVED
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Structured AI output. Sensitive: never logged, never returned outside the owner scope.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONColumn, nullable=False, default=dict)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONColumn, nullable=False, default=dict)
    rejection_reason: Mapped[str | None] = mapped_column(String(500))
