"""ORM model registry.

Importing this package registers every table on ``Base.metadata`` so that
Alembic autogeneration and test schema creation see the full schema.
"""

from app.models.audit import AuditLog, AuditLogImmutableError
from app.models.biomarker import LabResult
from app.models.consent import ConsentGrant, ShareLink
from app.models.document import Document, DocumentExtraction
from app.models.emergency import EmergencyContact, Reminder
from app.models.insurance import (
    AyushmanCard,
    Claim,
    ClaimDocument,
    Hospitalisation,
    InsuranceCoverageFact,
    InsuranceExtractionRequest,
    InsuranceInsuredMember,
    InsurancePolicy,
    InsurancePolicyDocument,
    InsurancePolicyVersion,
    Insurer,
    InsurerVerificationAttempt,
)
from app.models.medication import InteractionRule, Medication, MedicationSchedule
from app.models.patient import FamilyMember, PatientProfile
from app.models.record import HealthRecord, RecordRevision
from app.models.user import AuthSession, User
from app.models.wellness import HerbDrugOverlapRule, WellnessRecord

__all__ = [
    "AuditLog",
    "AuditLogImmutableError",
    "AuthSession",
    "AyushmanCard",
    "Claim",
    "ClaimDocument",
    "ConsentGrant",
    "Document",
    "DocumentExtraction",
    "EmergencyContact",
    "FamilyMember",
    "HealthRecord",
    "HerbDrugOverlapRule",
    "Hospitalisation",
    "InteractionRule",
    "InsuranceCoverageFact",
    "InsuranceExtractionRequest",
    "InsuranceInsuredMember",
    "InsurancePolicy",
    "InsurancePolicyDocument",
    "InsurancePolicyVersion",
    "Insurer",
    "InsurerVerificationAttempt",
    "LabResult",
    "Medication",
    "MedicationSchedule",
    "PatientProfile",
    "RecordRevision",
    "Reminder",
    "ShareLink",
    "User",
    "WellnessRecord",
]
