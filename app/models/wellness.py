"""AYUSH and other wellness records, plus herb–drug evidence rules.

Care systems are stored on every record so allopathic and AYUSH data are never
silently merged. Herb names are stored as documented, with the botanical name
kept separately.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import JSONColumn, Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    CareSystem,
    InteractionSeverity,
    ReviewStatus,
    VerificationStatus,
    enum_type,
)


class WellnessRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "wellness_records"
    __table_args__ = (Index("ix_wellness_records_patient_system", "patient_id", "care_system"),)

    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patient_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    care_system: Mapped[CareSystem] = mapped_column(
        enum_type(CareSystem, 20), nullable=False, default=CareSystem.OTHER
    )
    # consultation | herbal_formulation | therapy | practice | other
    record_type: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    practitioner_name: Mapped[str | None] = mapped_column(String(200))
    facility_name: Mapped[str | None] = mapped_column(String(200))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # [{"name": "Ashwagandha", "botanical_name": "Withania somnifera",
    #   "part": "root", "form": "powder", "dose_text": "as advised"}]
    herbs: Mapped[list[dict[str, Any]]] = mapped_column(JSONColumn, nullable=False, default=list)
    formulation_name: Mapped[str | None] = mapped_column(String(200))
    documented_ingredients: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONColumn, nullable=False, default=list
    )
    notes: Mapped[str | None] = mapped_column(String(1000))

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


class HerbDrugOverlapRule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Curated herb–drug overlap entry with explicit evidence and review state.

    Ships empty: content must be imported from a citable reference and reviewed
    professionally. Every surfaced warning carries its evidence text, citation
    and ``review_status`` so the frontend can label it as unverified.
    """

    __tablename__ = "herb_drug_overlap_rules"
    __table_args__ = (
        UniqueConstraint(
            "herb_key",
            "drug_ingredient_key",
            "source_reference",
            name="uq_herb_drug_overlap_pair_source",
        ),
    )

    herb_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    drug_ingredient_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    severity: Mapped[InteractionSeverity] = mapped_column(
        enum_type(InteractionSeverity, 20), nullable=False
    )
    evidence_summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500))
    review_status: Mapped[ReviewStatus] = mapped_column(
        enum_type(ReviewStatus, 20), nullable=False, default=ReviewStatus.UNREVIEWED
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(200))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
