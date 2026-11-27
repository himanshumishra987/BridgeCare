"""Boundary contract with the AI engine.

Status: **proposed v1, to be confirmed with the AI engine owner.** The shapes
below mirror the capabilities announced for ``feature/ai-engine`` (document
classification, structured biomarker/medication/clinical-event extraction and
source provenance), but they must be signed off before either side relies on
them. ``extra="forbid"`` is intentional: an undocumented field is an error
rather than silently discarded, so drift is caught immediately.

The AI engine never sets ``verified``; records arrive as ``pending_review`` and
only a human (owner, guardian, or clinician with a records grant) may verify.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationAppError
from app.models.biomarker import LabResult
from app.models.document import Document, DocumentExtraction
from app.models.enums import (
    ActorType,
    DocumentKind,
    DocumentStatus,
    ExtractionStatus,
    MedicationStatus,
    RecordCategory,
    RecordOrigin,
    VerificationStatus,
)
from app.models.medication import Medication
from app.models.patient import PatientProfile
from app.models.record import HealthRecord
from app.services.audit import record_audit
from app.services.records import create_record

ANALYTE_KEY_PATTERN = r"^[a-z0-9_]{2,64}$"


class SourceProvenanceIn(BaseModel):
    """Where in the source document a value came from.

    ``snippet_sha256`` is a digest of the source snippet, not the snippet
    itself: prose from a medical document must not travel through the backend.
    """

    model_config = ConfigDict(extra="forbid")

    page: int | None = Field(default=None, ge=1)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    section: str | None = Field(default=None, max_length=120)
    snippet_sha256: str | None = Field(default=None, min_length=8, max_length=64)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    model_version: str | None = Field(default=None, max_length=60)


class IngredientIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    strength: str | None = Field(default=None, max_length=40)
    unit: str | None = Field(default=None, max_length=24)


class BiomarkerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    collected_at: datetime
    lab_name: str | None = Field(default=None, max_length=200)
    fasting: bool | None = None
    method: str | None = Field(default=None, max_length=100)
    source: SourceProvenanceIn


class MedicationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_name: str | None = Field(default=None, max_length=200)
    generic_name: str | None = Field(default=None, max_length=200)
    active_ingredients: list[IngredientIn] = Field(default_factory=list, max_length=20)
    form: str | None = Field(default=None, max_length=60)
    route: str | None = Field(default=None, max_length=60)
    status: MedicationStatus = MedicationStatus.ACTIVE
    started_on: str | None = None  # ISO date, validated on ingest
    ended_on: str | None = None
    prescribed_by: str | None = Field(default=None, max_length=200)
    dose_text: str | None = Field(default=None, max_length=255)
    indication: str | None = Field(default=None, max_length=200)
    source: SourceProvenanceIn


class ClinicalEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: RecordCategory
    title: str = Field(min_length=1, max_length=200)
    summary: str | None = None
    recorded_at: datetime
    provider_name: str | None = Field(default=None, max_length=200)
    facility_name: str | None = Field(default=None, max_length=200)
    source: SourceProvenanceIn


class ExtractionEnvelope(BaseModel):
    """One document's worth of structured extraction."""

    model_config = ConfigDict(extra="forbid")

    contract_version: str = Field(min_length=1, max_length=40)
    extraction_id: str = Field(min_length=8, max_length=64)
    document_id: uuid.UUID
    patient_id: uuid.UUID
    engine_version: str = Field(min_length=1, max_length=40)
    received_at: datetime
    document_kind: DocumentKind | None = None
    # Only a pending-review claim is acceptable; anything else is a contract violation.
    verification_status: Literal["pending_review"] | None = None
    biomarkers: list[BiomarkerIn] = Field(default_factory=list, max_length=200)
    medications: list[MedicationIn] = Field(default_factory=list, max_length=100)
    clinical_events: list[ClinicalEventIn] = Field(default_factory=list, max_length=100)
    provenance: SourceProvenanceIn | None = None


def _parse_date(value: str | None, field: str) -> Any:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationAppError(f"{field} must be an ISO date (YYYY-MM-DD).") from exc


def ingest_extraction(
    db: Session, *, envelope: ExtractionEnvelope, request: Request | None = None
) -> dict[str, Any]:
    """Persist a validated extraction. Idempotent on ``extraction_id``."""
    settings = get_settings()
    if envelope.contract_version != settings.ai_contract_version:
        raise ValidationAppError(
            "Unsupported AI contract version '"
            f"{envelope.contract_version}'. The backend implements "
            f"'{settings.ai_contract_version}'."
        )
    if envelope.verification_status not in (None, "pending_review"):
        raise ValidationAppError(
            "The AI engine may only submit records for human review (pending_review)."
        )

    patient = db.get(PatientProfile, envelope.patient_id)
    if patient is None:
        raise NotFoundError("Patient profile not found.")

    document = db.get(Document, envelope.document_id)
    if document is None or document.patient_id != patient.id:
        raise NotFoundError("Document not found for this patient.")
    if document.archived_at is not None:
        raise ConflictError("The document has been archived.")

    existing = db.scalar(
        select(DocumentExtraction).where(
            DocumentExtraction.extraction_id == envelope.extraction_id
        )
    )
    if existing is not None:
        if existing.document_id != document.id or existing.patient_id != patient.id:
            raise ConflictError("extraction_id was already used for a different document.")
        return {
            "extraction_id": existing.extraction_id,
            "status": str(existing.status),
            "created": False,
            "records_created": 0,
            "measurements_created": 0,
            "medications_created": 0,
        }

    receipt = DocumentExtraction(
        document_id=document.id,
        patient_id=patient.id,
        extraction_id=envelope.extraction_id,
        engine_version=envelope.engine_version,
        contract_version=envelope.contract_version,
        status=ExtractionStatus.ACCEPTED,
        received_at=envelope.received_at,
        payload=envelope.model_dump(mode="json"),
        provenance=(envelope.provenance.model_dump(mode="json") if envelope.provenance else {}),
    )
    db.add(receipt)
    db.flush()

    records_created = 0
    for event in envelope.clinical_events:
        create_record(
            db,
            patient_id=patient.id,
            category=event.category,
            title=event.title,
            recorded_at=event.recorded_at,
            summary=event.summary,
            provider_name=event.provider_name,
            facility_name=event.facility_name,
            origin=RecordOrigin.AI_ENGINE,
            created_by_user_id=None,
            status=VerificationStatus.PENDING_REVIEW,
            source_document_id=document.id,
            source_extraction_id=receipt.id,
            provenance=event.source.model_dump(mode="json"),
        )
        records_created += 1

    measurements_created = 0
    for biomarker in envelope.biomarkers:
        db.add(
            LabResult(
                patient_id=patient.id,
                analyte_key=biomarker.analyte_key,
                analyte_display=biomarker.analyte_display,
                value_numeric=biomarker.value_numeric,
                value_text=biomarker.value_text,
                unit=biomarker.unit,
                original_unit=biomarker.original_unit or biomarker.unit,
                original_value_text=biomarker.original_value_text,
                ref_low=biomarker.ref_low,
                ref_high=biomarker.ref_high,
                ref_text=biomarker.ref_text,
                lab_name=biomarker.lab_name,
                collected_at=biomarker.collected_at,
                fasting=biomarker.fasting,
                method=biomarker.method,
                source_document_id=document.id,
                verification_status=VerificationStatus.PENDING_REVIEW,
            )
        )
        measurements_created += 1

    medications_created = 0
    for item in envelope.medications:
        db.add(
            Medication(
                patient_id=patient.id,
                brand_name=item.brand_name,
                generic_name=item.generic_name,
                active_ingredients=[ingredient.model_dump() for ingredient in item.active_ingredients],
                form=item.form,
                route=item.route,
                status=item.status,
                started_on=_parse_date(item.started_on, "started_on"),
                ended_on=_parse_date(item.ended_on, "ended_on"),
                prescribed_by=item.prescribed_by,
                dose_text=item.dose_text,
                indication=item.indication,
                source_document_id=document.id,
                verification_status=VerificationStatus.PENDING_REVIEW,
            )
        )
        medications_created += 1

    if envelope.document_kind is not None and document.kind == DocumentKind.UNKNOWN:
        document.kind = envelope.document_kind
    document.status = DocumentStatus.EXTRACTED
    db.flush()

    record_audit(
        db,
        action="ai.extraction.ingested",
        actor_type=ActorType.AI_SERVICE,
        patient_id=patient.id,
        resource_type="document",
        resource_id=str(document.id),
        request=request,
        context={
            "extraction_id": envelope.extraction_id,
            "contract_version": envelope.contract_version,
            "engine_version": envelope.engine_version,
            "records_created": records_created,
            "measurements_created": measurements_created,
            "medications_created": medications_created,
        },
    )

    return {
        "extraction_id": receipt.extraction_id,
        "status": str(receipt.status),
        "created": True,
        "records_created": records_created,
        "measurements_created": measurements_created,
        "medications_created": medications_created,
        "verification_status": VerificationStatus.PENDING_REVIEW.value,
    }


def utc_now() -> datetime:
    return datetime.now(UTC)
