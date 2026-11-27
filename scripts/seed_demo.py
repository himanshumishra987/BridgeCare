"""Seed synthetic demo data.

All data created here is invented for demonstrations. Never run this against a
database that contains real patient information.

Requirements
------------
* The schema must already exist: run ``alembic upgrade head`` first.
* ``BRIDGECARE_SEED_PASSWORD`` must be set (the script refuses to guess a password
  and never prints it).

Usage
-----
    BRIDGECARE_SEED_PASSWORD='<a strong demo password>' \\
        python scripts/seed_demo.py
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import get_session_factory  # noqa: E402
from app.models.consent import ConsentGrant  # noqa: E402
from app.models.emergency import EmergencyContact, Reminder  # noqa: E402
from app.models.enums import (  # noqa: E402
    AccessScope,
    CareSystem,
    ClaimStatus,
    ConsentBasis,
    ConsentStatus,
    CoverageSource,
    MedicationStatus,
    PolicyStatus,
    PolicyType,
    RecordCategory,
    RecordOrigin,
    ReminderKind,
    SexAtBirth,
    UserRole,
    VerificationStatus,
)
from app.models.insurance import Claim, InsurancePolicy  # noqa: E402
from app.models.medication import Medication, MedicationSchedule  # noqa: E402
from app.models.patient import PatientProfile  # noqa: E402
from app.models.record import HealthRecord  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.wellness import WellnessRecord  # noqa: E402
from app.models.biomarker import LabResult  # noqa: E402

DEMO_EMAIL = "demo.patient@bridgecare.example"
CAREGIVER_EMAIL = "demo.caregiver@bridgecare.example"
PASSWORD_ENV = "BRIDGECARE_SEED_PASSWORD"


def _measurement(patient_id, analyte_key, display, value, unit, taken, low=None, high=None):
    return LabResult(
        patient_id=patient_id,
        analyte_key=analyte_key,
        analyte_display=display,
        value_numeric=Decimal(value),
        unit=unit,
        original_unit=unit,
        original_value_text=value,
        ref_low=Decimal(low) if low else None,
        ref_high=Decimal(high) if high else None,
        ref_text=f"{low} - {high} {unit}" if low and high else None,
        lab_name="Sunrise Diagnostics (demo)",
        collected_at=taken,
        verification_status=VerificationStatus.VERIFIED,
    )


def seed() -> int:
    password = os.environ.get(PASSWORD_ENV)
    if not password:
        print(f"Refusing to seed without {PASSWORD_ENV} set.", file=sys.stderr)
        return 2

    session_factory = get_session_factory()
    with session_factory() as db:
        existing = db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if existing is not None:
            print("Demo data already present; nothing to do.")
            return 0

        now = datetime.now(UTC)
        today = now.date()

        patient_user = User(
            email=DEMO_EMAIL,
            password_hash=hash_password(password),
            full_name="Demo Patient",
            role=UserRole.PATIENT,
        )
        caregiver_user = User(
            email=CAREGIVER_EMAIL,
            password_hash=hash_password(password),
            full_name="Demo Caregiver",
            role=UserRole.CAREGIVER,
        )
        db.add_all([patient_user, caregiver_user])
        db.flush()

        profile = PatientProfile(
            user_id=patient_user.id,
            display_name="Demo Patient",
            date_of_birth=date(1979, 4, 12),
            sex_at_birth=SexAtBirth.FEMALE,
            blood_group="O+",
            primary_language="en",
            allergy_summary="Penicillin (rash)",
            condition_summary="Type 2 diabetes, hypertension",
        )
        db.add(profile)
        db.flush()

        records = [
            HealthRecord(
                patient_id=profile.id,
                category=RecordCategory.LAB_REPORT,
                title="Quarterly HbA1c panel",
                summary="Synthetic demo record for trend charts.",
                recorded_at=now - timedelta(days=90),
                provider_name="Dr. Iyer (demo)",
                facility_name="Sunrise Diagnostics (demo)",
                status=VerificationStatus.VERIFIED,
                origin=RecordOrigin.USER,
                created_by_user_id=patient_user.id,
                provenance={"page": 1, "confidence": 0.94},
            ),
            HealthRecord(
                patient_id=profile.id,
                category=RecordCategory.CONSULTATION,
                title="Diabetes follow-up",
                summary="Synthetic demo consultation note.",
                recorded_at=now - timedelta(days=30),
                provider_name="Dr. Iyer (demo)",
                facility_name="City Clinic (demo)",
                status=VerificationStatus.VERIFIED,
                origin=RecordOrigin.USER,
                created_by_user_id=patient_user.id,
                provenance={},
            ),
            HealthRecord(
                patient_id=profile.id,
                category=RecordCategory.PRESCRIPTION,
                title="Metformin prescription",
                summary="Synthetic demo prescription.",
                recorded_at=now - timedelta(days=120),
                provider_name="Dr. Iyer (demo)",
                status=VerificationStatus.PENDING_REVIEW,
                origin=RecordOrigin.AI_ENGINE,
                provenance={"page": 1, "confidence": 0.88},
            ),
        ]
        db.add_all(records)

        db.add_all(
            [
                _measurement(profile.id, "hba1c", "HbA1c", "7.6", "%", now - timedelta(days=270), "4.0", "5.6"),
                _measurement(profile.id, "hba1c", "HbA1c", "7.1", "%", now - timedelta(days=180), "4.0", "5.6"),
                _measurement(profile.id, "hba1c", "HbA1c", "6.6", "%", now - timedelta(days=90), "4.0", "5.6"),
                _measurement(profile.id, "hba1c", "HbA1c", "6.4", "%", now - timedelta(days=5), "4.0", "5.6"),
                _measurement(profile.id, "hemoglobin", "Hemoglobin", "132", "g/L", now - timedelta(days=90), "120", "160"),
                _measurement(profile.id, "hemoglobin", "Hemoglobin", "13.5", "g/dL", now - timedelta(days=5), "12.0", "16.0"),
                _measurement(profile.id, "ldl_cholesterol", "LDL cholesterol", "3.1", "mmol/L", now - timedelta(days=90), "0", "2.6"),
                _measurement(profile.id, "ldl_cholesterol", "LDL cholesterol", "112", "mg/dL", now - timedelta(days=5), "0", "100"),
            ]
        )

        metformin = Medication(
            patient_id=profile.id,
            brand_name="Glucophage (demo)",
            generic_name="metformin",
            active_ingredients=[{"name": "metformin", "strength": "500", "unit": "mg"}],
            status=MedicationStatus.ACTIVE,
            started_on=today - timedelta(days=400),
            prescribed_by="Dr. Iyer (demo)",
            dose_text="500 mg twice daily as prescribed",
            verification_status=VerificationStatus.VERIFIED,
            created_by_user_id=patient_user.id,
        )
        amlodipine = Medication(
            patient_id=profile.id,
            brand_name="Amlopress (demo)",
            generic_name="amlodipine",
            active_ingredients=[{"name": "amlodipine", "strength": "5", "unit": "mg"}],
            status=MedicationStatus.ACTIVE,
            started_on=today - timedelta(days=200),
            prescribed_by="Dr. Iyer (demo)",
            dose_text="5 mg once daily as prescribed",
            verification_status=VerificationStatus.VERIFIED,
            created_by_user_id=patient_user.id,
        )
        db.add_all([metformin, amlodipine])
        db.flush()

        schedule = MedicationSchedule(
            medication_id=metformin.id,
            patient_id=profile.id,
            frequency="twice_daily",
            times=["08:00", "20:00"],
            timezone="Asia/Kolkata",
            start_date=today - timedelta(days=400),
            instructions_text="As prescribed",
        )
        db.add(schedule)
        db.flush()

        db.add(
            Reminder(
                patient_id=profile.id,
                kind=ReminderKind.MEDICATION,
                title="Morning metformin",
                due_at=now + timedelta(hours=8),
                recurrence="daily",
                timezone="Asia/Kolkata",
                medication_schedule_id=schedule.id,
                created_by_user_id=patient_user.id,
            )
        )

        db.add(
            WellnessRecord(
                patient_id=profile.id,
                care_system=CareSystem.AYURVEDA,
                record_type="herbal_formulation",
                title="Ashwagandha churna (demo)",
                practitioner_name="Vaidya Sharma (demo)",
                recorded_at=now - timedelta(days=45),
                herbs=[
                    {
                        "name": "Ashwagandha",
                        "botanical_name": "Withania somnifera",
                        "part": "root",
                        "form": "powder",
                        "dose_text": "as advised",
                    }
                ],
                formulation_name="Ashwagandha Churna (demo)",
                documented_ingredients=[{"name": "Withania somnifera"}],
                verification_status=VerificationStatus.UNVERIFIED,
                created_by_user_id=patient_user.id,
            )
        )

        db.add(
            EmergencyContact(
                patient_id=profile.id,
                name="Demo Sister",
                relationship="sibling",
                phone="9000000000",
                is_primary=True,
            )
        )

        policy = InsurancePolicy(
            patient_id=profile.id,
            insurer_name_text="Example Health Insurance (demo)",
            policy_number="DEMO-POLICY-0001",
            policy_type=PolicyType.HEALTH,
            holder_name="Demo Patient",
            valid_from=today - timedelta(days=300),
            valid_to=today + timedelta(days=65),
            sum_insured=Decimal("500000"),
            currency="INR",
            coverage_source=CoverageSource.USER_ENTERED,
            status=PolicyStatus.ACTIVE,
            created_by_user_id=patient_user.id,
        )
        db.add(policy)
        db.flush()
        db.add(
            Claim(
                patient_id=profile.id,
                policy_id=policy.id,
                claim_number="DEMO-CLAIM-0001",
                submitted_on=today - timedelta(days=20),
                user_reported_status=ClaimStatus.SUBMITTED,
                user_status_updated_at=now,
                created_by_user_id=patient_user.id,
            )
        )

        db.add(
            ConsentGrant(
                patient_id=profile.id,
                grantee_user_id=caregiver_user.id,
                granted_by_user_id=patient_user.id,
                scopes=[scope.value for scope in AccessScope],
                purpose="care_coordination",
                basis=ConsentBasis.PATIENT_CONSENT,
                status=ConsentStatus.ACTIVE,
                accepted_at=now,
            )
        )

        db.commit()

        print("Synthetic demo data created.")
        print(f"  patient account:  {DEMO_EMAIL}")
        print(f"  caregiver account:{CAREGIVER_EMAIL}")
        print(f"  patient profile:  {profile.id}")
        print("  records=3 measurements=8 medications=2 reminders=1 wellness=1")
        print("  policy=1 claim=1 emergency_contacts=1 consent=1 (caregiver, active)")
        print("Password comes from BRIDGECARE_SEED_PASSWORD and is never printed.")
        return 0


if __name__ == "__main__":
    raise SystemExit(seed())
