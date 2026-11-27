from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import EmailStr, Field

from app.models.enums import SexAtBirth
from app.schemas.common import ORMModel, StrictModel


class EmergencyContactCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    relationship: str | None = Field(default=None, max_length=80)
    phone: str = Field(min_length=3, max_length=32)
    alternate_phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    is_primary: bool = False
    notes: str | None = Field(default=None, max_length=255)


class EmergencyContactUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    relationship: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, min_length=3, max_length=32)
    alternate_phone: str | None = Field(default=None, max_length=32)
    email: EmailStr | None = None
    is_primary: bool | None = None
    notes: str | None = Field(default=None, max_length=255)


class EmergencyContactOut(ORMModel):
    id: uuid.UUID
    name: str
    relationship: str | None = None
    phone: str
    alternate_phone: str | None = None
    email: EmailStr | None = None
    is_primary: bool
    notes: str | None = None
    created_at: datetime


class EmergencyPatientOut(StrictModel):
    display_name: str
    date_of_birth: date | None = None
    sex_at_birth: SexAtBirth
    blood_group: str | None = None
    allergy_summary: str | None = None
    condition_summary: str | None = None


class EmergencyMedicationOut(StrictModel):
    display_name: str
    generic_name: str | None = None
    dose_text: str | None = None
    started_on: date | None = None


class EmergencyEventOut(StrictModel):
    title: str
    category: str
    recorded_at: datetime
    verification_status: str


class EmergencySummaryOut(StrictModel):
    """Emergency view: verified events and active medicines only, never documents."""

    patient: EmergencyPatientOut
    active_medications: list[EmergencyMedicationOut]
    recent_verified_events: list[EmergencyEventOut]
    emergency_contacts: list[EmergencyContactOut]
    generated_at: datetime
    disclosure_note: str
    access_scope: str


class HospitalOut(StrictModel):
    name: str
    address: str | None = None
    phone: str | None = None
    distance_km: float | None = None
    source: str | None = None


class HospitalSearchOut(StrictModel):
    provider: str
    provider_configured: bool
    hospitals: list[HospitalOut]
    note: str | None = None
