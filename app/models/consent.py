"""Consent grants and public share links."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSONColumn, Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import ConsentBasis, ConsentStatus, enum_type


class ConsentGrant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An explicit, scoped, expiring and revocable permission on a patient record.

    Consent is always two-sided: the patient (or guardian) creates the grant and
    the grantee must accept it before it becomes ``ACTIVE``. The access layer
    only honours ``ACTIVE``, unexpired, unrevoked grants.
    """

    __tablename__ = "consent_grants"
    __table_args__ = (
        Index("ix_consent_grants_lookup", "patient_id", "grantee_user_id", "status"),
    )

    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    grantee_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    granted_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    scopes: Mapped[list[str]] = mapped_column(JSONColumn, nullable=False, default=list)
    purpose: Mapped[str] = mapped_column(String(200), nullable=False, default="care_coordination")
    basis: Mapped[ConsentBasis] = mapped_column(
        enum_type(ConsentBasis, 30), nullable=False, default=ConsentBasis.PATIENT_CONSENT
    )
    status: Mapped[ConsentStatus] = mapped_column(
        enum_type(ConsentStatus, 20), nullable=False, default=ConsentStatus.PENDING, index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoked_reason: Mapped[str | None] = mapped_column(String(255))

    def scope_set(self) -> set[str]:
        return {str(scope) for scope in (self.scopes or [])}


class ShareLink(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A public, expiring, usage-limited link exposing a whitelisted record subset.

    Only a SHA-256 digest of the link token is persisted; the plaintext token is
    returned exactly once, at creation time.
    """

    __tablename__ = "share_links"

    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))
    scopes: Mapped[list[str]] = mapped_column(JSONColumn, nullable=False, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_uses: Mapped[int | None] = mapped_column(Integer)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def scope_set(self) -> set[str]:
        return {str(scope) for scope in (self.scopes or [])}

    def snapshot(self) -> dict[str, Any]:
        """Non-sensitive description returned to the owner."""
        return {
            "id": str(self.id),
            "label": self.label,
            "token_prefix": self.token_prefix,
            "scopes": list(self.scopes or []),
            "expires_at": self.expires_at,
            "max_uses": self.max_uses,
            "use_count": self.use_count,
            "revoked_at": self.revoked_at,
            "last_accessed_at": self.last_accessed_at,
        }
