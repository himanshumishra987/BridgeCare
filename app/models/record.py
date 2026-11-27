"""Structured health records, verification state and edit history."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSONColumn, Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    RecordCategory,
    RecordOrigin,
    VerificationStatus,
    enum_type,
)


class HealthRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A structured medical record belonging to exactly one patient.

    ``status`` is owned by the backend: the AI engine can only create
    ``PENDING_REVIEW`` rows, and only a human with write access can move a row
    to ``VERIFIED`` or ``REJECTED`` (see ``app/services/verification.py``).
    """

    __tablename__ = "health_records"
    __table_args__ = (
        Index("ix_health_records_chronology", "patient_id", "recorded_at"),
        Index("ix_health_records_status", "patient_id", "status"),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    category: Mapped[RecordCategory] = mapped_column(
        enum_type(RecordCategory, 30), nullable=False, default=RecordCategory.OTHER, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_name: Mapped[str | None] = mapped_column(String(200))
    facility_name: Mapped[str | None] = mapped_column(String(200))

    status: Mapped[VerificationStatus] = mapped_column(
        enum_type(VerificationStatus, 20),
        nullable=False,
        default=VerificationStatus.UNVERIFIED,
    )
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verification_note: Mapped[str | None] = mapped_column(String(500))

    origin: Mapped[RecordOrigin] = mapped_column(
        enum_type(RecordOrigin, 20), nullable=False, default=RecordOrigin.USER
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_extraction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_extractions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Page numbers, character spans, model version, confidence: kept verbatim.
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONColumn, nullable=False, default=dict)


class RecordRevision(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Append-only history of edits and verification transitions."""

    __tablename__ = "record_revisions"
    __table_args__ = (
        UniqueConstraint("record_id", "revision_number", name="uq_record_revisions_record_number"),
    )

    record_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("health_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    edited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    change_type: Mapped[str] = mapped_column(String(30), nullable=False, default="edit")
    change_reason: Mapped[str | None] = mapped_column(String(255))
    before: Mapped[dict[str, Any]] = mapped_column(JSONColumn, nullable=False, default=dict)
    after: Mapped[dict[str, Any]] = mapped_column(JSONColumn, nullable=False, default=dict)
