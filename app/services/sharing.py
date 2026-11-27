"""Consent-aware sharing infrastructure.

Two independent mechanisms exist:

1. ``ConsentGrant`` — authenticated, granular, per-user permission (see
   ``app/services/access.py``).
2. ``ShareLink`` — an unauthenticated, expiring, usage-limited, revocable link
   created deliberately by the owner or guardian for a whitelisted subset.

Public links are limited to a whitelist of scopes and never expose insurance,
family or emergency data, document bytes or another patient's identifiers.
Every resolution is audited.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import NotFoundError, ValidationAppError
from app.core.security import hash_token, new_opaque_token, token_fingerprint
from app.models.consent import ShareLink
from app.models.enums import (
    SHARE_LINK_BLOCKED_SCOPES,
    AccessScope,
    ActorType,
    AuditOutcome,
)
from app.models.patient import PatientProfile
from app.services import analytics as analytics_service
from app.services.audit import record_audit

LINK_INVALID_MESSAGE = "This share link is invalid, expired or has been revoked."


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def validate_share_scopes(scopes: list[str]) -> list[AccessScope]:
    if not scopes:
        raise ValidationAppError("At least one scope must be granted.")
    resolved: list[AccessScope] = []
    for raw in scopes:
        try:
            scope = AccessScope(raw)
        except ValueError as exc:
            raise ValidationAppError(f"Unknown scope: {raw}") from exc
        if scope in SHARE_LINK_BLOCKED_SCOPES:
            raise ValidationAppError(
                f"Scope '{scope.value}' cannot be shared through a public link; "
                "use a consent grant instead."
            )
        if scope not in resolved:
            resolved.append(scope)
    return resolved


def create_share_link(
    db: Session,
    *,
    patient: PatientProfile,
    created_by_user_id: uuid.UUID,
    scopes: list[str],
    expires_at: datetime,
    max_uses: int | None = None,
    label: str | None = None,
    request: Request | None = None,
) -> tuple[ShareLink, str]:
    settings = get_settings()
    resolved = validate_share_scopes(scopes)
    expires_at = _aware(expires_at)
    now = _now()
    if expires_at <= now:
        raise ValidationAppError("Expiry must be in the future.")
    if expires_at > now + timedelta(days=settings.share_link_max_days):
        raise ValidationAppError(
            f"Share links may last at most {settings.share_link_max_days} days."
        )
    if max_uses is not None and max_uses < 1:
        raise ValidationAppError("max_uses must be at least 1 when provided.")

    token = new_opaque_token()
    link = ShareLink(
        patient_id=patient.id,
        created_by_user_id=created_by_user_id,
        token_hash=hash_token(token),
        token_prefix=token_fingerprint(token),
        label=(label or "")[:120] or None,
        scopes=[scope.value for scope in resolved],
        expires_at=expires_at,
        max_uses=max_uses,
    )
    db.add(link)
    db.flush()
    record_audit(
        db,
        action="share_link.created",
        actor_user_id=created_by_user_id,
        patient_id=patient.id,
        resource_type="share_link",
        resource_id=str(link.id),
        request=request,
        context={"scopes": link.scopes, "expires_at": expires_at.isoformat()},
    )
    return link, token


def resolve_share_link(db: Session, *, token: str, request: Request | None = None) -> ShareLink:
    """Validate a public token and count the access. Raises 404 on any failure."""
    if not token or len(token) < 16:
        raise NotFoundError(LINK_INVALID_MESSAGE)
    link = db.scalar(select(ShareLink).where(ShareLink.token_hash == hash_token(token)))
    now = _now()
    if link is None or link.revoked_at is not None:
        raise NotFoundError(LINK_INVALID_MESSAGE)
    if _aware(link.expires_at) <= now:
        raise NotFoundError(LINK_INVALID_MESSAGE)
    if link.max_uses is not None and link.use_count >= link.max_uses:
        raise NotFoundError(LINK_INVALID_MESSAGE)

    link.use_count += 1
    link.last_accessed_at = now
    db.flush()
    record_audit(
        db,
        action="share_link.accessed",
        actor_type=ActorType.SHARE_LINK,
        patient_id=link.patient_id,
        resource_type="share_link",
        resource_id=str(link.id),
        outcome=AuditOutcome.SUCCESS,
        request=request,
        context={"scopes": link.scopes},
    )
    return link


def _records_view(db: Session, *, patient_id: uuid.UUID) -> list[dict[str, Any]]:
    from app.models.record import HealthRecord

    rows = db.scalars(
        select(HealthRecord)
        .where(HealthRecord.patient_id == patient_id)
        .order_by(HealthRecord.recorded_at.desc())
        .limit(200)
    )
    return [
        {
            "category": str(record.category),
            "title": record.title,
            "recorded_at": record.recorded_at,
            "provider_name": record.provider_name,
            "facility_name": record.facility_name,
            "summary": record.summary,
            "verification_status": str(record.status),
            "has_source_document": record.source_document_id is not None,
        }
        for record in rows
    ]


def _biomarkers_view(db: Session, *, patient_id: uuid.UUID) -> list[dict[str, Any]]:
    view: list[dict[str, Any]] = []
    for analyte in analytics_service.available_analytes(db, patient_id=patient_id)[:12]:
        series = analytics_service.build_series(
            db, patient_id=patient_id, analyte_key=analyte["analyte_key"]
        )
        view.append(
            {
                "analyte_key": series.analyte_key,
                "analyte_display": series.analyte_display,
                "unit": series.unit,
                "points": [
                    {
                        "collected_at": point.collected_at,
                        "value": point.value,
                        "ref_low": point.ref_low,
                        "ref_high": point.ref_high,
                        "verification_status": point.verification_status,
                    }
                    for point in series.points[-24:]
                ],
            }
        )
    return view


def _medications_view(db: Session, *, patient_id: uuid.UUID) -> list[dict[str, Any]]:
    from app.models.medication import Medication

    rows = db.scalars(
        select(Medication)
        .where(Medication.patient_id == patient_id)
        .order_by(Medication.started_on.desc().nullslast())
    )
    return [
        {
            "brand_name": medication.brand_name,
            "generic_name": medication.generic_name,
            "active_ingredients": [
                {"name": ingredient.get("name")} for ingredient in medication.active_ingredients or []
            ],
            "status": str(medication.status),
            "dose_text": medication.dose_text,
            "started_on": medication.started_on,
            "ended_on": medication.ended_on,
            "verification_status": str(medication.verification_status),
        }
        for medication in rows
    ]


def _wellness_view(db: Session, *, patient_id: uuid.UUID) -> list[dict[str, Any]]:
    from app.models.wellness import WellnessRecord

    rows = db.scalars(
        select(WellnessRecord)
        .where(WellnessRecord.patient_id == patient_id)
        .order_by(WellnessRecord.recorded_at.desc())
    )
    return [
        {
            "care_system": str(record.care_system),
            "record_type": record.record_type,
            "title": record.title,
            "recorded_at": record.recorded_at,
            "formulation_name": record.formulation_name,
            "herbs": [
                {"name": herb.get("name"), "botanical_name": herb.get("botanical_name")}
                for herb in record.herbs or []
            ],
            "verification_status": str(record.verification_status),
        }
        for record in rows
    ]


def build_shared_view(db: Session, *, link: ShareLink) -> dict[str, Any]:
    """Whitelisted, scope-limited projection for a public link."""
    patient = db.get(PatientProfile, link.patient_id)
    if patient is None:
        raise NotFoundError(LINK_INVALID_MESSAGE)

    scopes = link.scope_set()
    payload: dict[str, Any] = {
        "share": {
            "label": link.label,
            "scopes": sorted(scopes),
            "expires_at": link.expires_at,
        },
        "generated_at": _now(),
        "disclaimer": (
            "Shared by the record holder. Information may be incomplete and is not a "
            "medical diagnosis."
        ),
    }

    if AccessScope.DEMOGRAPHICS.value in scopes:
        payload["patient"] = {
            "display_name": patient.display_name,
            "date_of_birth": patient.date_of_birth,
            "sex_at_birth": str(patient.sex_at_birth),
            "blood_group": patient.blood_group,
            "allergy_summary": patient.allergy_summary,
            "condition_summary": patient.condition_summary,
        }
    if AccessScope.RECORDS.value in scopes:
        payload["records"] = _records_view(db, patient_id=patient.id)
    if AccessScope.BIOMARKERS.value in scopes:
        payload["biomarkers"] = _biomarkers_view(db, patient_id=patient.id)
    if AccessScope.MEDICATIONS.value in scopes:
        payload["medications"] = _medications_view(db, patient_id=patient.id)
    if AccessScope.WELLNESS.value in scopes:
        payload["wellness"] = _wellness_view(db, patient_id=patient.id)
    return payload
