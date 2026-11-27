from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from app.models.enums import (
    CareSystem,
    InteractionSeverity,
    MedicationStatus,
    ReminderChannel,
    ReminderKind,
    ReviewStatus,
    VerificationStatus,
)
from app.schemas.common import ORMModel, StrictModel

_TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


class IngredientSchema(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    strength: str | None = Field(default=None, max_length=40)
    unit: str | None = Field(default=None, max_length=24)


class MedicationCreate(StrictModel):
    brand_name: str | None = Field(default=None, max_length=200)
    generic_name: str | None = Field(default=None, max_length=200)
    active_ingredients: list[IngredientSchema] = Field(default_factory=list, max_length=20)
    form: str | None = Field(default=None, max_length=60)
    route: str | None = Field(default=None, max_length=60)
    status: MedicationStatus = MedicationStatus.ACTIVE
    started_on: date | None = None
    ended_on: date | None = None
    prescribed_by: str | None = Field(default=None, max_length=200)
    dose_text: str | None = Field(default=None, max_length=255)
    indication: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)
    source_record_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _identifiable(self) -> MedicationCreate:
        if not (self.brand_name or self.generic_name or self.active_ingredients):
            raise ValueError("Provide a brand name, generic name or at least one ingredient.")
        if self.started_on and self.ended_on and self.ended_on < self.started_on:
            raise ValueError("ended_on must not precede started_on.")
        return self


class MedicationUpdate(StrictModel):
    brand_name: str | None = Field(default=None, max_length=200)
    generic_name: str | None = Field(default=None, max_length=200)
    active_ingredients: list[IngredientSchema] | None = Field(default=None, max_length=20)
    form: str | None = Field(default=None, max_length=60)
    route: str | None = Field(default=None, max_length=60)
    status: MedicationStatus | None = None
    started_on: date | None = None
    ended_on: date | None = None
    prescribed_by: str | None = Field(default=None, max_length=200)
    dose_text: str | None = Field(default=None, max_length=255)
    indication: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=1000)


class MedicationOut(ORMModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    brand_name: str | None = None
    generic_name: str | None = None
    active_ingredients: list[dict[str, Any]]
    form: str | None = None
    route: str | None = None
    status: MedicationStatus
    started_on: date | None = None
    ended_on: date | None = None
    prescribed_by: str | None = None
    dose_text: str | None = None
    indication: str | None = None
    notes: str | None = None
    verification_status: VerificationStatus
    created_at: datetime
    updated_at: datetime


class MedicationStopRequest(StrictModel):
    ended_on: date | None = None
    reason: str | None = Field(default=None, max_length=255)


class MedicationScheduleCreate(StrictModel):
    frequency: Literal[
        "once_daily",
        "twice_daily",
        "three_times_daily",
        "four_times_daily",
        "weekly",
        "as_needed",
        "custom",
    ] = "once_daily"
    times: list[str] = Field(default_factory=list, max_length=8)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    start_date: date | None = None
    end_date: date | None = None
    instructions_text: str | None = Field(default=None, max_length=255)

    @field_validator("times")
    @classmethod
    def _times_are_hh_mm(cls, value: list[str]) -> list[str]:
        import re

        for item in value:
            if not re.match(_TIME_PATTERN, item):
                raise ValueError("Times must use 24-hour HH:MM format.")
        return value

    @model_validator(mode="after")
    def _consistent(self) -> MedicationScheduleCreate:
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date.")
        if self.frequency in {"once_daily", "twice_daily", "three_times_daily", "four_times_daily", "weekly"} and not self.times:
            raise ValueError("A scheduled frequency requires at least one time.")
        return self


class MedicationScheduleOut(ORMModel):
    id: uuid.UUID
    medication_id: uuid.UUID
    frequency: str
    times: list[str]
    timezone: str
    start_date: date | None = None
    end_date: date | None = None
    instructions_text: str | None = None
    is_active: bool
    created_at: datetime


class ReminderCreate(StrictModel):
    kind: ReminderKind = ReminderKind.CUSTOM
    title: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=500)
    due_at: datetime
    recurrence: Literal["none", "daily", "weekly", "monthly"] = "none"
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    channel: ReminderChannel = ReminderChannel.IN_APP
    medication_schedule_id: uuid.UUID | None = None


class ReminderUpdate(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=500)
    due_at: datetime | None = None
    recurrence: Literal["none", "daily", "weekly", "monthly"] | None = None
    channel: ReminderChannel | None = None
    is_enabled: bool | None = None
    completed: bool | None = None


class ReminderOut(ORMModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    kind: ReminderKind
    title: str
    notes: str | None = None
    due_at: datetime
    recurrence: str
    timezone: str
    channel: ReminderChannel
    is_enabled: bool
    acknowledged_at: datetime | None = None
    completed_at: datetime | None = None
    medication_schedule_id: uuid.UUID | None = None
    created_at: datetime


class MedicationRefOut(StrictModel):
    id: str
    display_name: str
    brand_name: str | None = None
    generic_name: str | None = None
    started_on: date | None = None
    ended_on: date | None = None
    status: str | None = None


class DuplicateGroupOut(StrictModel):
    ingredient_key: str
    medications: list[MedicationRefOut]


class OverlapSideOut(StrictModel):
    id: str
    display_name: str
    started_on: date | None = None
    ended_on: date | None = None


class PrescriptionOverlapOut(StrictModel):
    ingredient_keys: list[str]
    overlap_start: date | None = None
    overlap_end: date | None = None
    left: OverlapSideOut
    right: OverlapSideOut


class WarningMedicationOut(StrictModel):
    id: str
    display_name: str


class InteractionWarningOut(StrictModel):
    severity: InteractionSeverity
    summary: str
    source_reference: str
    source_url: str | None = None
    professional_review_status: ReviewStatus
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    medications: list[WarningMedicationOut]
    advice: str | None = None
    disclaimer: str


class InteractionWarningsOut(StrictModel):
    warnings: list[InteractionWarningOut]
    rules_reviewed: int
    disclaimer: str


# --------------------------------------------------------------------------- wellness
class HerbSchema(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    botanical_name: str | None = Field(default=None, max_length=160)
    part: str | None = Field(default=None, max_length=60)
    form: str | None = Field(default=None, max_length=60)
    dose_text: str | None = Field(default=None, max_length=255)


class WellnessCreate(StrictModel):
    care_system: CareSystem
    record_type: Literal[
        "consultation", "herbal_formulation", "therapy", "practice", "other"
    ] = "other"
    title: str = Field(min_length=1, max_length=200)
    practitioner_name: str | None = Field(default=None, max_length=200)
    facility_name: str | None = Field(default=None, max_length=200)
    recorded_at: datetime
    herbs: list[HerbSchema] = Field(default_factory=list, max_length=50)
    formulation_name: str | None = Field(default=None, max_length=200)
    documented_ingredients: list[IngredientSchema] = Field(default_factory=list, max_length=50)
    notes: str | None = Field(default=None, max_length=1000)
    source_document_id: uuid.UUID | None = None


class WellnessOut(ORMModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    care_system: CareSystem
    record_type: str
    title: str
    practitioner_name: str | None = None
    facility_name: str | None = None
    recorded_at: datetime
    herbs: list[dict[str, Any]]
    formulation_name: str | None = None
    documented_ingredients: list[dict[str, Any]]
    notes: str | None = None
    verification_status: VerificationStatus
    created_at: datetime


class HerbDrugOverlapOut(StrictModel):
    severity: InteractionSeverity
    herb_key: str
    drug_ingredient_key: str
    evidence_summary: str
    source_reference: str
    source_url: str | None = None
    professional_review_status: ReviewStatus
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    care_system: str
    wellness_record: dict[str, Any]
    medication: dict[str, Any]
    requires_professional_review: bool
    disclaimer: str


class HerbDrugOverlapsOut(StrictModel):
    overlaps: list[HerbDrugOverlapOut]
    care_systems_evaluated: list[str] = Field(default_factory=list)
    note: str | None = None
    disclaimer: str
