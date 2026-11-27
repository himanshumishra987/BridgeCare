"""Longitudinal biomarker and analytics endpoints.

Trend responses are built by ``app/services/analytics.py``, which guarantees a
single canonical unit per series and reports excluded measurements explicitly.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import NotFoundError, ValidationAppError
from app.core.pagination import paginate
from app.models.biomarker import LabResult
from app.models.enums import AccessScope, VerificationStatus
from app.models.record import HealthRecord
from app.schemas.clinical import (
    AnalyticsSummaryOut,
    AnalyteOut,
    ExcludedPointOut,
    LabResultCreate,
    LabResultOut,
    SeriesOut,
    SeriesPointOut,
)
from app.schemas.common import PageMeta, Paginated
from app.services import analytics as analytics_service
from app.services.access import require_patient_access, require_patient_write_access
from app.services.audit import record_audit

router = APIRouter(tags=["Biomarkers & analytics"])

BIOMARKER_NOT_FOUND = "Measurement not found or not accessible."


def _to_series_out(series: analytics_service.Series) -> SeriesOut:
    return SeriesOut(
        analyte_key=series.analyte_key,
        analyte_display=series.analyte_display,
        unit=series.unit,
        comparable=series.comparable,
        points=[
            SeriesPointOut(
                collected_at=point.collected_at,
                value=float(point.value) if point.value is not None else None,
                unit=point.unit,
                ref_low=float(point.ref_low) if point.ref_low is not None else None,
                ref_high=float(point.ref_high) if point.ref_high is not None else None,
                ref_text=point.ref_text,
                original_value_text=point.original_value_text,
                original_unit=point.original_unit,
                lab_name=point.lab_name,
                verification_status=point.verification_status,
                source_record_id=point.source_record_id,
                converted=point.converted,
            )
            for point in series.points
        ],
        excluded=[
            ExcludedPointOut(
                id=item["id"],
                collected_at=item["collected_at"],
                unit=item["unit"],
                reason=item["reason"],
            )
            for item in series.excluded
        ],
    )


@router.post(
    "/patients/{patient_id}/biomarkers",
    response_model=LabResultOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a biomarker measurement with its original unit and reference range",
)
def add_measurement(
    patient_id: uuid.UUID,
    payload: LabResultCreate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> LabResult:
    require_patient_write_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.BIOMARKERS,
        request=request,
        action="biomarker.create",
    )
    source_document_id = None
    if payload.source_record_id is not None:
        record = db.get(HealthRecord, payload.source_record_id)
        if record is None or record.patient_id != patient_id:
            raise ValidationAppError("Source record does not belong to this patient.")
        source_document_id = record.source_document_id

    result = LabResult(
        patient_id=patient_id,
        analyte_key=payload.analyte_key.strip().lower(),
        analyte_display=payload.analyte_display,
        value_numeric=payload.value_numeric,
        value_text=payload.value_text,
        unit=payload.unit,
        original_unit=payload.original_unit or payload.unit,
        original_value_text=payload.original_value_text,
        ref_low=payload.ref_low,
        ref_high=payload.ref_high,
        ref_text=payload.ref_text,
        lab_name=payload.lab_name,
        collected_at=payload.collected_at,
        fasting=payload.fasting,
        method=payload.method,
        source_record_id=payload.source_record_id,
        source_document_id=source_document_id,
        verification_status=VerificationStatus.UNVERIFIED,
        created_by_user_id=user.id,
    )
    db.add(result)
    db.flush()
    record_audit(
        db,
        action="biomarker.created",
        actor_user_id=user.id,
        actor_role=str(user.role),
        patient_id=patient_id,
        resource_type="lab_result",
        resource_id=str(result.id),
        request=request,
        context={"analyte_key": result.analyte_key},
    )
    return result


@router.get(
    "/patients/{patient_id}/biomarkers",
    response_model=Paginated[LabResultOut],
    summary="List measurements, newest first",
)
def list_measurements(
    patient_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    page: int = 1,
    page_size: int | None = None,
    analyte_key: str | None = None,
    collected_from: datetime | None = None,
    collected_to: datetime | None = None,
) -> Paginated[LabResultOut]:
    require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.BIOMARKERS,
        request=request,
        action="biomarker.list",
    )
    stmt = select(LabResult).where(LabResult.patient_id == patient_id)
    if analyte_key:
        stmt = stmt.where(LabResult.analyte_key == analyte_key.strip().lower())
    if collected_from is not None:
        stmt = stmt.where(LabResult.collected_at >= collected_from)
    if collected_to is not None:
        stmt = stmt.where(LabResult.collected_at <= collected_to)
    stmt = stmt.order_by(LabResult.collected_at.desc())
    page_result = paginate(db, stmt, page=page, page_size=page_size)
    return Paginated[LabResultOut](
        items=[LabResultOut.model_validate(item) for item in page_result.items],
        meta=PageMeta(**page_result.meta()),
    )


@router.get(
    "/patients/{patient_id}/biomarkers/analytes",
    response_model=list[AnalyteOut],
    summary="Analytes available for trend charts",
)
def list_analytes(
    patient_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> list[AnalyteOut]:
    require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.BIOMARKERS,
        request=request,
        action="biomarker.analytes",
    )
    return [
        AnalyteOut.model_validate(item)
        for item in analytics_service.available_analytes(db, patient_id=patient_id)
    ]


@router.get(
    "/patients/{patient_id}/biomarkers/{analyte_key}/trend",
    response_model=SeriesOut,
    summary="Comparable trend series for one analyte",
)
def analyte_trend(
    patient_id: uuid.UUID,
    analyte_key: str,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> SeriesOut:
    require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.ANALYTICS,
        request=request,
        action="analytics.trend",
    )
    if not analyte_key.strip():
        raise NotFoundError(BIOMARKER_NOT_FOUND)
    series = analytics_service.build_series(
        db, patient_id=patient_id, analyte_key=analyte_key
    )
    if not series.points and not series.excluded and not series.unit:
        raise NotFoundError(BIOMARKER_NOT_FOUND)
    return _to_series_out(series)


@router.get(
    "/patients/{patient_id}/analytics/summary",
    response_model=AnalyticsSummaryOut,
    summary="Counts used by the health dashboard",
)
def analytics_summary(
    patient_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> AnalyticsSummaryOut:
    require_patient_access(
        db,
        user=user,
        patient_id=patient_id,
        scope=AccessScope.ANALYTICS,
        request=request,
        action="analytics.summary",
    )
    return AnalyticsSummaryOut.model_validate(
        analytics_service.summary(db, patient_id=patient_id)
    )
