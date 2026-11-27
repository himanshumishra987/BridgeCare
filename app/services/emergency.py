"""Emergency support.

The emergency summary is intentionally minimal: identity basics, allergies,
conditions, active medication *names and recorded dose text*, and only
human-verified recent events. Documents, free-text notes and unverified
extractions are excluded so an emergency disclosure cannot leak more than the
patient intended.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.emergency import EmergencyContact
from app.models.enums import MedicationStatus, VerificationStatus
from app.models.medication import Medication
from app.models.patient import PatientProfile
from app.models.record import HealthRecord
from app.services.medications import medication_display_name

EMERGENCY_DISCLOSURE_NOTE = (
    "This summary is disclosed for emergency care only. It may be incomplete and "
    "must not be used as a diagnosis. Access to this summary is recorded."
)


@dataclass(frozen=True)
class HospitalSearchResult:
    provider: str
    provider_configured: bool
    hospitals: list[dict[str, Any]]
    note: str | None = None


def build_emergency_summary(db: Session, *, patient: PatientProfile) -> dict[str, Any]:
    meds = db.scalars(
        select(Medication)
        .where(
            Medication.patient_id == patient.id,
            Medication.status == MedicationStatus.ACTIVE,
        )
        .order_by(Medication.started_on.desc().nullslast())
    )
    events = db.scalars(
        select(HealthRecord)
        .where(
            HealthRecord.patient_id == patient.id,
            HealthRecord.status == VerificationStatus.VERIFIED,
        )
        .order_by(HealthRecord.recorded_at.desc())
        .limit(10)
    )
    contacts = db.scalars(
        select(EmergencyContact)
        .where(EmergencyContact.patient_id == patient.id)
        .order_by(EmergencyContact.is_primary.desc(), EmergencyContact.name.asc())
    )

    return {
        "patient": {
            "display_name": patient.display_name,
            "date_of_birth": patient.date_of_birth,
            "sex_at_birth": patient.sex_at_birth,
            "blood_group": patient.blood_group,
            "allergy_summary": patient.allergy_summary,
            "condition_summary": patient.condition_summary,
        },
        "active_medications": [
            {
                "display_name": medication_display_name(medication),
                "generic_name": medication.generic_name,
                "dose_text": medication.dose_text,
                "started_on": medication.started_on,
            }
            for medication in meds
        ],
        "recent_verified_events": [
            {
                "title": record.title,
                "category": str(record.category),
                "recorded_at": record.recorded_at,
                "verification_status": str(record.status),
            }
            for record in events
        ],
        "emergency_contacts": [
            {
                "id": contact.id,
                "name": contact.name,
                "relationship": contact.relationship,
                "phone": contact.phone,
                "alternate_phone": contact.alternate_phone,
                "email": contact.email,
                "is_primary": contact.is_primary,
                "notes": contact.notes,
                "created_at": contact.created_at,
            }
            for contact in contacts
        ],
        "generated_at": datetime.now(UTC),
        "disclosure_note": EMERGENCY_DISCLOSURE_NOTE,
        "access_scope": "emergency",
    }


def nearby_hospitals(
    *, latitude: float, longitude: float, radius_km: float = 10.0
) -> HospitalSearchResult:
    """Integration point for a hospital directory provider.

    No provider is bundled, so the endpoint reports that honestly instead of
    inventing facilities. Implementing a provider means returning the same
    shape from this function.
    """
    provider = (get_settings().hospital_directory_provider or "none").strip().lower()
    if provider in {"", "none"}:
        return HospitalSearchResult(
            provider="none",
            provider_configured=False,
            hospitals=[],
            note=(
                "Hospital discovery is not configured on this deployment. Set "
                "BRIDGECARE_HOSPITAL_DIRECTORY_PROVIDER and install the provider adapter "
                "to enable it. In an emergency, call local emergency services."
            ),
        )
    raise NotImplementedError(
        f"Hospital directory provider '{provider}' has no adapter in this build."
    )
