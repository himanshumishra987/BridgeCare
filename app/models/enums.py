"""Enumerations shared by the ORM models, schemas and services.

All enums are stored as plain VARCHAR rather than native database enums, so
migrations stay portable between PostgreSQL and SQLite and adding a value never
requires an ``ALTER TYPE``. Membership is enforced in Python (``validate_strings``
plus the ORM type); the schema deliberately carries no CHECK constraint, so a
value written by raw SQL outside this application is not rejected by the database.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


def enum_type(enum_cls: type[StrEnum], length: int = 40) -> SAEnum:
    """SQLAlchemy enum column storing the member *value*, portable across dialects."""
    return SAEnum(
        enum_cls,
        name=enum_cls.__name__.lower(),
        native_enum=False,
        length=length,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


class UserRole(StrEnum):
    PATIENT = "patient"
    CAREGIVER = "caregiver"
    CLINICIAN = "clinician"
    ADMIN = "admin"


class AccessScope(StrEnum):
    """Granular permission a patient can grant on their own record."""

    DEMOGRAPHICS = "demographics"
    DOCUMENTS = "documents"
    RECORDS = "records"
    BIOMARKERS = "biomarkers"
    MEDICATIONS = "medications"
    WELLNESS = "wellness"
    EMERGENCY = "emergency"
    INSURANCE = "insurance"
    FAMILY = "family"
    ANALYTICS = "analytics"


#: Scopes implied by ``AccessScope.RECORDS`` is deliberately *not* a superset:
#: each module is granted explicitly so a caregiver can be limited to, say,
#: medications without seeing psychiatric records.
ALL_SCOPES: frozenset[AccessScope] = frozenset(AccessScope)

#: Scopes that may never be granted through a public share link.
SHARE_LINK_BLOCKED_SCOPES: frozenset[AccessScope] = frozenset(
    {AccessScope.INSURANCE, AccessScope.FAMILY, AccessScope.EMERGENCY}
)


class ConsentBasis(StrEnum):
    PATIENT_CONSENT = "patient_consent"
    GUARDIANSHIP = "guardianship"
    EMERGENCY = "emergency"


class ConsentStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    DECLINED = "declined"
    REVOKED = "revoked"
    EXPIRED = "expired"


class VerificationStatus(StrEnum):
    """Human verification state of a medical record.

    The AI engine may only ever produce ``PENDING_REVIEW``; only a human with
    write access may move a record to ``VERIFIED``.
    """

    UNVERIFIED = "unverified"
    PENDING_REVIEW = "pending_review"
    VERIFIED = "verified"
    REJECTED = "rejected"


class RecordCategory(StrEnum):
    LAB_REPORT = "lab_report"
    PRESCRIPTION = "prescription"
    DIAGNOSIS = "diagnosis"
    IMAGING = "imaging"
    DISCHARGE_SUMMARY = "discharge_summary"
    CONSULTATION = "consultation"
    VACCINATION = "vaccination"
    OTHER = "other"


class RecordOrigin(StrEnum):
    USER = "user"
    AI_ENGINE = "ai_engine"


class DocumentKind(StrEnum):
    LAB_REPORT = "lab_report"
    PRESCRIPTION = "prescription"
    DISCHARGE_SUMMARY = "discharge_summary"
    IMAGING_REPORT = "imaging_report"
    INSURANCE = "insurance"
    OTHER = "other"
    UNKNOWN = "unknown"


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    EXTRACTED = "extracted"
    FAILED = "failed"
    ARCHIVED = "archived"


class DocumentSource(StrEnum):
    USER_UPLOAD = "user_upload"
    AI_ENGINE = "ai_engine"


class ExtractionStatus(StrEnum):
    RECEIVED = "received"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class MedicationStatus(StrEnum):
    ACTIVE = "active"
    STOPPED = "stopped"
    COMPLETED = "completed"
    UNKNOWN = "unknown"


class ReminderKind(StrEnum):
    MEDICATION = "medication"
    APPOINTMENT = "appointment"
    VACCINATION = "vaccination"
    CHECKUP = "checkup"
    CUSTOM = "custom"


class ReminderChannel(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"
    SMS = "sms"


class CareSystem(StrEnum):
    AYURVEDA = "ayurveda"
    YOGA = "yoga"
    UNANI = "unani"
    SIDDHA = "siddha"
    HOMOEOPATHY = "homoeopathy"
    NATUROPATHY = "naturopathy"
    OTHER = "other"


class InteractionSeverity(StrEnum):
    MINOR = "minor"
    MODERATE = "moderate"
    MAJOR = "major"
    CONTRAINDICATED = "contraindicated"


class ReviewStatus(StrEnum):
    """Professional review state for clinical knowledge-base entries."""

    UNREVIEWED = "unreviewed"
    IN_REVIEW = "in_review"
    REVIEWED = "reviewed"


class PolicyType(StrEnum):
    HEALTH = "health"
    CRITICAL_ILLNESS = "critical_illness"
    TOP_UP = "top_up"
    GOVERNMENT_SCHEME = "government_scheme"
    OTHER = "other"


class CoverageSource(StrEnum):
    USER_ENTERED = "user_entered"
    DOCUMENT = "document"
    INSURER_VERIFIED = "insurer_verified"


class PolicyStatus(StrEnum):
    ACTIVE = "active"
    LAPSED = "lapsed"
    UNKNOWN = "unknown"


class ClaimStatus(StrEnum):
    """User-reported claim state. Never treated as insurer confirmation."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    INFORMATION_REQUESTED = "information_requested"
    APPROVED = "approved"
    PARTIALLY_APPROVED = "partially_approved"
    REJECTED = "rejected"
    SETTLED = "settled"
    UNKNOWN = "unknown"


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    ERROR = "error"


class ActorType(StrEnum):
    USER = "user"
    AI_SERVICE = "ai_service"
    SHARE_LINK = "share_link"
    SYSTEM = "system"


class SexAtBirth(StrEnum):
    FEMALE = "female"
    MALE = "male"
    INTERSEX = "intersex"
    UNKNOWN = "unknown"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


class FamilyRelationship(StrEnum):
    SPOUSE = "spouse"
    PARENT = "parent"
    CHILD = "child"
    SIBLING = "sibling"
    GRANDPARENT = "grandparent"
    GRANDCHILD = "grandchild"
    GUARDIAN = "guardian"
    OTHER = "other"


class PolicyCoverageClass(StrEnum):
    """Individual cover versus one shared sum insured for several people."""

    INDIVIDUAL = "individual"
    FAMILY_FLOATER = "family_floater"


class CoverageVerificationStatus(StrEnum):
    """How a single coverage value came to be, and how far it is trusted.

    Only the insurer verification integration may produce ``INSURER_VERIFIED``;
    a patient confirmation is recorded separately and never upgraded silently.
    """

    EXTRACTED = "extracted"
    MANUALLY_ENTERED = "manually_entered"
    PATIENT_CONFIRMED = "patient_confirmed"
    INSURER_VERIFIED = "insurer_verified"
    DISCREPANCY = "discrepancy"
    NEEDS_REVIEW = "needs_review"


class CoverageFactSource(StrEnum):
    EXTRACTED = "extracted"
    MANUAL = "manual"
    INSURER = "insurer"


class PolicyDocumentRole(StrEnum):
    POLICY_COPY = "policy_copy"
    ENDORSEMENT = "endorsement"
    WORDING = "wording"
    INVOICE = "invoice"
    OTHER = "other"


class PolicyVersionKind(StrEnum):
    CREATED = "created"
    MANUAL_UPDATE = "manual_update"
    EXTRACTION = "extraction"
    PATIENT_CONFIRMATION = "patient_confirmation"
    ENDORSEMENT = "endorsement"
    INSURER_VERIFICATION = "insurer_verification"


class DocumentScanStatus(StrEnum):
    """IDTA verdict. Anything other than ``CLEAN`` blocks AI processing."""

    PENDING = "pending"
    CLEAN = "clean"
    INFECTED = "infected"
    ERROR = "error"


class ExtractionRequestStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class InsurerVerificationOutcome(StrEnum):
    VERIFIED = "verified"
    DISCREPANCY = "discrepancy"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"
