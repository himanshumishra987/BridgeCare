from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.models.enums import (
    DocumentKind,
    DocumentScanStatus,
    DocumentSource,
    DocumentStatus,
    ExtractionStatus,
    RecordCategory,
    RecordOrigin,
    VerificationStatus,
)
from app.schemas.common import ORMModel, StrictModel

ANALYTE_KEY_PATTERN = r"^[a-z0-9_]{2,64}$"


# --------------------------------------------------------------------------- documents
class DocumentOut(ORMModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    kind: DocumentKind
    status: DocumentStatus
    source: DocumentSource
    original_filename: str
    content_type: str
    byte_size: int
    sha256: str
    page_count: int | None = None
    created_at: datetime
    archived_at: datetime | None = None
    # IDTA verdict: ``clean`` is the only value that permits AI processing.
    scan_status: DocumentScanStatus
    scanned_at: datetime | None = None
    scan_engine: str | None = None
    scan_signature_version: str | None = None
    quarantined_at: datetime | None = None


class DocumentExtractionOut(ORMModel):
    id: uuid.UUID
    document_id: uuid.UUID
    extraction_id: str
    engine_version: str | None = None
    contract_version: str
    status: ExtractionStatus
    received_at: datetime
    rejection_reason: str | None = None


# --------------------------------------------------------------------------- records
class RecordCreate(StrictModel):
    category: RecordCategory
    title: str = Field(min_length=1, max_length=200)
    recorded_at: datetime
    summary: str | None = Field(default=None, max_length=20000)
    provider_name: str | None = Field(default=None, max_length=200)
    facility_name: str | None = Field(default=None, max_length=200)
    source_document_id: uuid.UUID | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class RecordUpdate(StrictModel):
    category: RecordCategory | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    recorded_at: datetime | None = None
    summary: str | None = Field(default=None, max_length=20000)
    provider_name: str | None = Field(default=None, max_length=200)
    facility_name: str | None = Field(default=None, max_length=200)
    provenance: dict[str, Any] | None = None
    change_reason: str | None = Field(default=None, max_length=255)


class RecordOut(ORMModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    category: RecordCategory
    title: str
    summary: str | None = None
    recorded_at: datetime
    provider_name: str | None = None
    facility_name: str | None = None
    status: VerificationStatus
    verified_at: datetime | None = None
    verified_by_user_id: uuid.UUID | None = None
    verification_note: str | None = None
    origin: RecordOrigin
    source_document_id: uuid.UUID | None = None
    source_extraction_id: uuid.UUID | None = None
    provenance: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class RecordVerifyRequest(StrictModel):
    status: Literal["verified", "rejected", "pending_review"]
    note: str | None = Field(default=None, max_length=500)


class RecordRevisionOut(ORMModel):
    id: uuid.UUID
    revision_number: int
    change_type: str
    change_reason: str | None = None
    edited_by_user_id: uuid.UUID | None = None
    before: dict[str, Any]
    after: dict[str, Any]
    created_at: datetime


class TimelineEntryOut(StrictModel):
    entry_type: str
    occurred_at: datetime
    title: str
    category: str
    verification_status: str
    id: str
    source_document_id: str | None = None


# --------------------------------------------------------------------------- biomarkers
class LabResultCreate(StrictModel):
    analyte_key: str = Field(pattern=ANALYTE_KEY_PATTERN)
    analyte_display: str = Field(min_length=1, max_length=120)
    value_numeric: Decimal | None = None
    value_text: str | None = Field(default=None, max_length=64)
    unit: str = Field(min_length=1, max_length=32)
    original_unit: str | None = Field(default=None, max_length=32)
    original_value_text: str | None = Field(default=None, max_length=64)
    ref_low: Decimal | None = None
    ref_high: Decimal | None = None
    ref_text: str | None = Field(default=None, max_length=64)
    lab_name: str | None = Field(default=None, max_length=200)
    collected_at: datetime
    fasting: bool | None = None
    method: str | None = Field(default=None, max_length=100)
    source_record_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _value_present(self) -> LabResultCreate:
        if self.value_numeric is None and not self.value_text:
            raise ValueError("Provide value_numeric or value_text.")
        if (
            self.ref_low is not None
            and self.ref_high is not None
            and self.ref_low > self.ref_high
        ):
            raise ValueError("ref_low must not exceed ref_high.")
        return self


class LabResultOut(ORMModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    analyte_key: str
    analyte_display: str
    value_numeric: Decimal | None = None
    value_text: str | None = None
    unit: str
    original_value_text: str | None = None
    original_unit: str | None = None
    ref_low: Decimal | None = None
    ref_high: Decimal | None = None
    ref_text: str | None = None
    lab_name: str | None = None
    collected_at: datetime
    fasting: bool | None = None
    method: str | None = None
    source_record_id: uuid.UUID | None = None
    source_document_id: uuid.UUID | None = None
    verification_status: VerificationStatus
    created_at: datetime


class SeriesPointOut(StrictModel):
    collected_at: datetime
    value: float | None = None
    unit: str
    ref_low: float | None = None
    ref_high: float | None = None
    ref_text: str | None = None
    original_value_text: str | None = None
    original_unit: str | None = None
    lab_name: str | None = None
    verification_status: str
    source_record_id: str | None = None
    converted: bool = False


class ExcludedPointOut(StrictModel):
    id: str
    collected_at: datetime
    unit: str
    reason: str


class SeriesOut(StrictModel):
    analyte_key: str
    analyte_display: str
    unit: str
    comparable: bool
    points: list[SeriesPointOut]
    excluded: list[ExcludedPointOut]


class AnalyteOut(StrictModel):
    analyte_key: str
    analyte_display: str
    measurement_count: int
    latest_collected_at: datetime | None = None
    canonical_unit: str


class AnalyticsSummaryOut(StrictModel):
    record_count: int
    verified_record_count: int
    records_by_category: dict[str, int]
    measurement_count: int
    analyte_count: int
    active_medication_count: int
    pending_reminder_count: int
