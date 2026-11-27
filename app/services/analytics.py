"""Longitudinal analytics.

Comparability rules
-------------------
A trend line is only produced for measurements that share a canonical unit.
Values are converted to that canonical unit with an explicit, documented factor;
the original value and unit are always preserved and returned alongside. A
measurement whose unit cannot be converted for that analyte is **excluded** from
the series and reported in ``excluded`` — it is never silently coerced, and two
different analytes are never plotted on the same series.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.biomarker import LabResult
from app.models.enums import VerificationStatus
from app.models.medication import Medication, MedicationStatus
from app.models.record import HealthRecord
from app.models.emergency import Reminder

#: Canonical unit per analyte. Keys are the shared analyte vocabulary that the
#: AI engine must emit (see app/services/ai_contract.py).
CANONICAL_UNITS: dict[str, str] = {
    "hemoglobin": "g/dL",
    "hba1c": "%",
    "fasting_glucose": "mg/dL",
    "glucose": "mg/dL",
    "postprandial_glucose": "mg/dL",
    "ldl_cholesterol": "mg/dL",
    "hdl_cholesterol": "mg/dL",
    "total_cholesterol": "mg/dL",
    "triglycerides": "mg/dL",
    "creatinine": "mg/dL",
    "urea": "mg/dL",
    "tsh": "mIU/L",
    "vitamin_d": "ng/mL",
    "vitamin_b12": "pg/mL",
    "platelet_count": "10^3/uL",
    "wbc_count": "10^3/uL",
    "sgpt": "U/L",
    "sgot": "U/L",
    "bilirubin_total": "mg/dL",
    "sodium": "mmol/L",
    "potassium": "mmol/L",
    "egfr": "mL/min/1.73m2",
}

#: (analyte_key, normalized source unit) -> (canonical unit, multiplicative factor)
UNIT_CONVERSIONS: dict[tuple[str, str], tuple[str, Decimal]] = {}


def _register(analyte: str, canonical: str, conversions: dict[str, str]) -> None:
    UNIT_CONVERSIONS[(analyte, _normalize_unit(canonical))] = (canonical, Decimal("1"))
    for unit, factor in conversions.items():
        UNIT_CONVERSIONS[(analyte, _normalize_unit(unit))] = (canonical, Decimal(factor))


def _normalize_unit(unit: str) -> str:
    # Micro sign and Greek mu are both used for micromoles.
    return unit.strip().replace("µ", "u").replace("μ", "u").lower()


_LIPIDS = [
    "ldl_cholesterol",
    "hdl_cholesterol",
    "total_cholesterol",
]
for _analyte in _LIPIDS:
    _register(_analyte, "mg/dL", {"mmol/L": "38.67"})

for _analyte in ("fasting_glucose", "glucose", "postprandial_glucose"):
    _register(_analyte, "mg/dL", {"mmol/L": "18.0182"})

_register("hemoglobin", "g/dL", {"g/L": "0.1"})
_register("hba1c", "%", {})
_register("creatinine", "mg/dL", {"umol/L": "0.0113122", "mg/L": "0.1"})
_register("urea", "mg/dL", {"mmol/L": "6.006"})
_register("triglycerides", "mg/dL", {"mmol/L": "88.57"})
_register("bilirubin_total", "mg/dL", {"umol/L": "0.0585"})
_register("tsh", "mIU/L", {"uIU/mL": "1", "mU/L": "1"})
_register("vitamin_d", "ng/mL", {"nmol/L": "0.4006"})
_register("vitamin_b12", "pg/mL", {"pmol/L": "1.3554"})
_register("platelet_count", "10^3/uL", {"10^9/L": "1"})
_register("wbc_count", "10^3/uL", {"10^9/L": "1"})
_register("sgpt", "U/L", {})
_register("sgot", "U/L", {})
_register("sodium", "mmol/L", {"mEq/L": "1"})
_register("potassium", "mmol/L", {"mEq/L": "1"})
_register("egfr", "mL/min/1.73m2", {})


@dataclass(frozen=True)
class SeriesPoint:
    collected_at: datetime
    value: Decimal | None
    unit: str
    ref_low: Decimal | None
    ref_high: Decimal | None
    ref_text: str | None
    original_value_text: str | None
    original_unit: str | None
    lab_name: str | None
    verification_status: str
    source_record_id: str | None
    converted: bool


@dataclass
class Series:
    analyte_key: str
    analyte_display: str
    unit: str
    points: list[SeriesPoint] = field(default_factory=list)
    excluded: list[dict[str, Any]] = field(default_factory=list)

    @property
    def comparable(self) -> bool:
        return len(self.points) >= 2


def canonicalize(analyte_key: str, unit: str) -> tuple[str, Decimal] | None:
    """Return (canonical_unit, factor) or None when conversion is not defined."""
    return UNIT_CONVERSIONS.get((analyte_key, _normalize_unit(unit)))


def build_series(db: Session, *, patient_id: uuid.UUID, analyte_key: str) -> Series:
    rows = list(
        db.scalars(
            select(LabResult)
            .where(
                LabResult.patient_id == patient_id,
                LabResult.analyte_key == analyte_key.strip().lower(),
            )
            .order_by(LabResult.collected_at.asc())
        )
    )
    key = analyte_key.strip().lower()
    display = rows[0].analyte_display if rows else key.replace("_", " ")

    if not rows:
        canonical_unit = CANONICAL_UNITS.get(key)
        return Series(
            analyte_key=key,
            analyte_display=display,
            unit=canonical_unit or "",
            points=[],
        )

    canonical_unit = CANONICAL_UNITS.get(key)
    if canonical_unit is None:
        # Unknown analyte: pick the most common unit and treat it as canonical,
        # still refusing to mix units within one series.
        counts = Counter(_normalize_unit(row.unit) for row in rows)
        canonical_unit = counts.most_common(1)[0][0]

    series = Series(analyte_key=key, analyte_display=display, unit=canonical_unit)
    for row in rows:
        conversion = canonicalize(key, row.unit)
        if conversion is None:
            if _normalize_unit(row.unit) == _normalize_unit(canonical_unit):
                target_unit, factor = canonical_unit, Decimal("1")
            else:
                series.excluded.append(
                    {
                        "id": str(row.id),
                        "collected_at": row.collected_at,
                        "unit": row.unit,
                        "reason": "unit_not_comparable",
                    }
                )
                continue
        else:
            target_unit, factor = conversion

        if _normalize_unit(target_unit) != _normalize_unit(canonical_unit):
            series.excluded.append(
                {
                    "id": str(row.id),
                    "collected_at": row.collected_at,
                    "unit": row.unit,
                    "reason": "different_canonical_unit",
                }
            )
            continue

        value = row.value_numeric
        converted_value = (Decimal(value) * factor) if value is not None else None
        series.points.append(
            SeriesPoint(
                collected_at=row.collected_at,
                value=converted_value,
                unit=canonical_unit,
                ref_low=(Decimal(row.ref_low) * factor) if row.ref_low is not None else None,
                ref_high=(Decimal(row.ref_high) * factor) if row.ref_high is not None else None,
                ref_text=row.ref_text,
                original_value_text=row.original_value_text,
                original_unit=row.original_unit,
                lab_name=row.lab_name,
                verification_status=str(row.verification_status),
                source_record_id=str(row.source_record_id) if row.source_record_id else None,
                converted=factor != Decimal("1"),
            )
        )
    return series


def available_analytes(db: Session, *, patient_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            LabResult.analyte_key,
            func.min(LabResult.analyte_display),
            func.count(LabResult.id),
            func.max(LabResult.collected_at),
        )
        .where(LabResult.patient_id == patient_id)
        .group_by(LabResult.analyte_key)
        .order_by(func.max(LabResult.collected_at).desc())
    ).all()
    return [
        {
            "analyte_key": row[0],
            "analyte_display": row[1],
            "measurement_count": int(row[2]),
            "latest_collected_at": row[3],
            "canonical_unit": CANONICAL_UNITS.get(row[0], ""),
        }
        for row in rows
    ]


def summary(db: Session, *, patient_id: uuid.UUID) -> dict[str, Any]:
    record_counts = dict(
        db.execute(
            select(HealthRecord.category, func.count(HealthRecord.id))
            .where(HealthRecord.patient_id == patient_id)
            .group_by(HealthRecord.category)
        ).all()
    )
    verified_count = (
        db.scalar(
            select(func.count(HealthRecord.id)).where(
                HealthRecord.patient_id == patient_id,
                HealthRecord.status == VerificationStatus.VERIFIED,
            )
        )
        or 0
    )
    measurement_count = (
        db.scalar(
            select(func.count(LabResult.id)).where(LabResult.patient_id == patient_id)
        )
        or 0
    )
    active_medications = (
        db.scalar(
            select(func.count(Medication.id)).where(
                Medication.patient_id == patient_id,
                Medication.status == MedicationStatus.ACTIVE,
            )
        )
        or 0
    )
    pending_reminders = (
        db.scalar(
            select(func.count(Reminder.id)).where(
                Reminder.patient_id == patient_id,
                Reminder.is_enabled.is_(True),
                Reminder.completed_at.is_(None),
            )
        )
        or 0
    )
    return {
        "record_count": sum(int(value) for value in record_counts.values()),
        "verified_record_count": int(verified_count),
        "records_by_category": {str(key): int(value) for key, value in record_counts.items()},
        "measurement_count": int(measurement_count),
        "analyte_count": len(available_analytes(db, patient_id=patient_id)),
        "active_medication_count": int(active_medications),
        "pending_reminder_count": int(pending_reminders),
    }
