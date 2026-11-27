"""Emergency contacts and general reminder infrastructure."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ReminderChannel, ReminderKind, enum_type


class EmergencyContact(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "emergency_contacts"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    relationship: Mapped[str | None] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    alternate_phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(320))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(String(255))


class Reminder(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Reminder records only.

    Delivery (push/e-mail/SMS) is out of scope for the backend foundation; this
    table is the scheduling source of truth a worker can poll by ``due_at``.
    """

    __tablename__ = "reminders"
    __table_args__ = (Index("ix_reminders_due", "patient_id", "is_enabled", "due_at"),)

    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[ReminderKind] = mapped_column(
        enum_type(ReminderKind, 20), nullable=False, default=ReminderKind.CUSTOM
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # none | daily | weekly | monthly
    recurrence: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    channel: Mapped[ReminderChannel] = mapped_column(
        enum_type(ReminderChannel, 20), nullable=False, default=ReminderChannel.IN_APP
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    medication_schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("medication_schedules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_ref_type: Mapped[str | None] = mapped_column(String(40))
    source_ref_id: Mapped[str | None] = mapped_column(String(64))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
