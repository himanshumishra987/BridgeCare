from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import Field

from app.models.enums import AccessScope, SexAtBirth
from app.schemas.common import ORMModel, StrictModel


class ShareLinkCreate(StrictModel):
    scopes: list[AccessScope] = Field(min_length=1, max_length=12)
    expires_in_days: int = Field(default=7, ge=1, le=365)
    max_uses: int | None = Field(default=None, ge=1, le=1000)
    label: str | None = Field(default=None, max_length=120)


class ShareLinkOut(ORMModel):
    id: uuid.UUID
    label: str | None = None
    token_prefix: str
    scopes: list[AccessScope]
    expires_at: datetime
    max_uses: int | None = None
    use_count: int
    revoked_at: datetime | None = None
    last_accessed_at: datetime | None = None
    created_at: datetime


class ShareLinkCreatedOut(StrictModel):
    link: ShareLinkOut
    token: str
    share_path: str


class SharedPatientOut(StrictModel):
    display_name: str
    date_of_birth: date | None = None
    sex_at_birth: SexAtBirth
    blood_group: str | None = None
    allergy_summary: str | None = None
    condition_summary: str | None = None


class SharedRecordOut(StrictModel):
    category: str
    title: str
    recorded_at: datetime
    provider_name: str | None = None
    facility_name: str | None = None
    summary: str | None = None
    verification_status: str
    has_source_document: bool


class SharedPointOut(StrictModel):
    collected_at: datetime
    value: float | None = None
    ref_low: float | None = None
    ref_high: float | None = None
    verification_status: str


class SharedSeriesOut(StrictModel):
    analyte_key: str
    analyte_display: str
    unit: str
    points: list[SharedPointOut]


class SharedMedicationOut(StrictModel):
    brand_name: str | None = None
    generic_name: str | None = None
    active_ingredients: list[dict[str, Any]]
    status: str
    dose_text: str | None = None
    started_on: date | None = None
    ended_on: date | None = None
    verification_status: str


class SharedWellnessOut(StrictModel):
    care_system: str
    record_type: str
    title: str
    recorded_at: datetime
    formulation_name: str | None = None
    herbs: list[dict[str, Any]]
    verification_status: str


class SharedViewOut(StrictModel):
    share: dict[str, Any]
    generated_at: datetime
    disclaimer: str
    patient: SharedPatientOut | None = None
    records: list[SharedRecordOut] | None = None
    biomarkers: list[SharedSeriesOut] | None = None
    medications: list[SharedMedicationOut] | None = None
    wellness: list[SharedWellnessOut] | None = None
