from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import EmailStr, Field, model_validator

from app.models.enums import AccessScope, ConsentBasis, ConsentStatus, FamilyRelationship, SexAtBirth
from app.schemas.common import ORMModel, StrictModel


class PatientProfileOut(ORMModel):
    id: uuid.UUID
    display_name: str
    date_of_birth: date | None = None
    sex_at_birth: SexAtBirth
    blood_group: str | None = None
    phone: str | None = None
    primary_language: str
    address_line: str | None = None
    allergy_summary: str | None = None
    condition_summary: str | None = None
    created_at: datetime
    updated_at: datetime


class PatientProfileUpdate(StrictModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    date_of_birth: date | None = None
    sex_at_birth: SexAtBirth | None = None
    blood_group: str | None = Field(default=None, max_length=8)
    phone: str | None = Field(default=None, max_length=32)
    primary_language: str | None = Field(default=None, min_length=2, max_length=16)
    address_line: str | None = Field(default=None, max_length=255)
    allergy_summary: str | None = Field(default=None, max_length=500)
    condition_summary: str | None = Field(default=None, max_length=500)


class PatientProfileSummary(ORMModel):
    id: uuid.UUID
    display_name: str
    date_of_birth: date | None = None
    sex_at_birth: SexAtBirth
    blood_group: str | None = None


class FamilyMemberCreate(StrictModel):
    """Create a dependant profile plus an explicit guardianship grant.

    ``guardianship_attested`` must be true: the relationship field alone is not
    treated as consent anywhere in the system.
    """

    display_name: str = Field(min_length=1, max_length=200)
    relationship: FamilyRelationship
    date_of_birth: date | None = None
    sex_at_birth: SexAtBirth = SexAtBirth.UNKNOWN
    blood_group: str | None = Field(default=None, max_length=8)
    is_dependent: bool = True
    guardianship_attested: bool
    notes: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _attestation_required(self) -> FamilyMemberCreate:
        if not self.guardianship_attested:
            raise ValueError(
                "guardianship_attested must be true; a family link alone grants no access."
            )
        return self


class FamilyMemberOut(ORMModel):
    id: uuid.UUID
    relationship: FamilyRelationship
    is_dependent: bool
    notes: str | None = None
    created_at: datetime
    profile: PatientProfileSummary


class ConsentCreate(StrictModel):
    grantee_email: EmailStr
    scopes: list[AccessScope] = Field(min_length=1, max_length=12)
    purpose: str = Field(default="care_coordination", min_length=2, max_length=200)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _unique_scopes(self) -> ConsentCreate:
        if len(set(self.scopes)) != len(self.scopes):
            raise ValueError("Scopes must not be repeated.")
        return self


class ConsentOut(ORMModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    grantee_user_id: uuid.UUID
    scopes: list[AccessScope]
    purpose: str
    basis: ConsentBasis
    status: ConsentStatus
    expires_at: datetime | None = None
    accepted_at: datetime | None = None
    revoked_at: datetime | None = None
    revoked_reason: str | None = None
    created_at: datetime


class ConsentWithPatientOut(ConsentOut):
    patient_display_name: str


#: Backwards-compatible alias used by the pending-consent listing.
PendingConsentOut = ConsentWithPatientOut


class ConsentRevokeRequest(StrictModel):
    reason: str | None = Field(default=None, max_length=255)
