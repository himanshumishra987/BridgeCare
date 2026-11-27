"""Longitudinal biomarker measurements.

A measurement keeps its *original* unit and value text alongside the canonical
unit, so analytics never silently reinterpret a lab result. Comparability is
decided by (analyte, canonical unit) in ``app/services/analytics.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import VerificationStatus, enum_type


class LabResult(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "lab_results"
    __table_args__ = (
        Index("ix_lab_results_series", "patient_id", "analyte_key", "collected_at"),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Canonical analyte slug, e.g. "hemoglobin", "hba1c", "ldl_cholesterol".
    analyte_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    analyte_display: Mapped[str] = mapped_column(String(120), nullable=False)

    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    value_text: Mapped[str | None] = mapped_column(String(64))
    unit: Mapped[str] = mapped_column(String(32), nullable=False)

    # Exactly as reported by the laboratory; never overwritten by conversion.
    original_value_text: Mapped[str | None] = mapped_column(String(64))
    original_unit: Mapped[str | None] = mapped_column(String(32))
    ref_low: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    ref_high: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    ref_text: Mapped[str | None] = mapped_column(String(64))

    lab_name: Mapped[str | None] = mapped_column(String(200))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fasting: Mapped[bool | None] = mapped_column(Boolean)
    method: Mapped[str | None] = mapped_column(String(100))

    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("health_records.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    verification_status: Mapped[VerificationStatus] = mapped_column(
        enum_type(VerificationStatus, 20),
        nullable=False,
        default=VerificationStatus.UNVERIFIED,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
