"""Medication history, schedules and curated interaction rules."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSONColumn, Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    InteractionSeverity,
    MedicationStatus,
    ReviewStatus,
    VerificationStatus,
    enum_type,
)


class Medication(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A medication the patient reports taking, as recorded.

    ``dose_text`` stores what the prescriber wrote. The backend never generates
    or adjusts dosage instructions; it only stores and displays them.
    """

    __tablename__ = "medications"
    __table_args__ = (Index("ix_medications_patient_status", "patient_id", "status"),)

    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    brand_name: Mapped[str | None] = mapped_column(String(200))
    generic_name: Mapped[str | None] = mapped_column(String(200), index=True)
    # [{"name": "paracetamol", "strength": "500", "unit": "mg"}]
    active_ingredients: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONColumn, nullable=False, default=list
    )
    form: Mapped[str | None] = mapped_column(String(60))
    route: Mapped[str | None] = mapped_column(String(60))

    status: Mapped[MedicationStatus] = mapped_column(
        enum_type(MedicationStatus, 20), nullable=False, default=MedicationStatus.ACTIVE
    )
    started_on: Mapped[date | None] = mapped_column(Date, index=True)
    ended_on: Mapped[date | None] = mapped_column(Date)
    prescribed_by: Mapped[str | None] = mapped_column(String(200))
    dose_text: Mapped[str | None] = mapped_column(String(255))
    indication: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(String(1000))

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


class MedicationSchedule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """When a medication is meant to be taken (user-entered or prescribed)."""

    __tablename__ = "medication_schedules"

    medication_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("medications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    frequency: Mapped[str] = mapped_column(String(40), nullable=False, default="once_daily")
    times: Mapped[list[str]] = mapped_column(JSONColumn, nullable=False, default=list)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    instructions_text: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class InteractionRule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A curated drug–drug interaction entry from a named reference.

    The table ships empty on purpose: interaction content is clinical knowledge
    that must be imported from a licensed reference and reviewed by a
    pharmacist or clinician before it is surfaced. Last-write metadata
    (``review_status``, ``reviewed_by``) is exposed with every warning.
    """

    __tablename__ = "interaction_rules"
    __table_args__ = (
        UniqueConstraint(
            "ingredient_a",
            "ingredient_b",
            "source_reference",
            name="uq_interaction_rules_pair_source",
        ),
        Index("ix_interaction_rules_pair", "ingredient_a", "ingredient_b"),
    )

    ingredient_a: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    ingredient_b: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    severity: Mapped[InteractionSeverity] = mapped_column(
        enum_type(InteractionSeverity, 20), nullable=False
    )
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500))
    review_status: Mapped[ReviewStatus] = mapped_column(
        enum_type(ReviewStatus, 20), nullable=False, default=ReviewStatus.UNREVIEWED
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(200))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
