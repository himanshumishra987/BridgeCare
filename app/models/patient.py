"""Patient health profiles and family membership."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import FamilyRelationship, SexAtBirth, enum_type


class PatientProfile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The subject of a health record.

    ``user_id`` is set only when the profile belongs to a person with their own
    account. Dependant profiles (children, elders) have ``user_id`` NULL and are
    reachable only through an explicit guardianship consent grant.
    """

    __tablename__ = "patient_profiles"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, unique=True, index=True
    )
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    sex_at_birth: Mapped[SexAtBirth] = mapped_column(
        enum_type(SexAtBirth, 20), nullable=False, default=SexAtBirth.UNKNOWN
    )
    blood_group: Mapped[str | None] = mapped_column(String(8))
    phone: Mapped[str | None] = mapped_column(String(32))
    primary_language: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    address_line: Mapped[str | None] = mapped_column(String(255))
    # Short, patient-authored summaries used by the emergency summary endpoint.
    allergy_summary: Mapped[str | None] = mapped_column(String(500))
    condition_summary: Mapped[str | None] = mapped_column(String(500))


class FamilyMember(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A link in a user's family list.

    Deliberately carries no permissions: being listed here grants nothing. All
    access flows through :class:`app.models.consent.ConsentGrant`, which is why
    "relationship alone must never grant access" holds structurally.
    """

    __tablename__ = "family_members"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "profile_id", name="uq_family_members_owner_profile"),
    )

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relationship: Mapped[FamilyRelationship] = mapped_column(
        enum_type(FamilyRelationship, 20), nullable=False
    )
    is_dependent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(String(255))
