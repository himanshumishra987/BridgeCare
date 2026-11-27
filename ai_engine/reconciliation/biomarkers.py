"""Biomarker normalization, comparability checks, and longitudinal trend analysis."""

from collections import defaultdict
from datetime import datetime
from typing import Optional

from ai_engine.schemas.common import FieldUncertainty, SourceReference
from ai_engine.schemas.reconciliation import (
    BiomarkerDataPoint,
    BiomarkerTrend,
    ConflictSeverity,
    CrossDocumentConflict,
    TrendDirection,
)
from ai_engine.schemas.summary import VerifiedRecordInput

_BIOMARKER_ALIASES: dict[str, str] = {
    "hb": "Hemoglobin",
    "hgb": "Hemoglobin",
    "hemoglobin": "Hemoglobin",
    "haemoglobin": "Hemoglobin",
    "fbs": "Fasting Glucose",
    "fasting glucose": "Fasting Glucose",
    "fasting blood glucose": "Fasting Glucose",
    "fasting blood sugar": "Fasting Glucose",
    "hba1c": "HbA1c",
    "a1c": "HbA1c",
    "glycated hemoglobin": "HbA1c",
    "tsh": "TSH",
    "thyroid stimulating hormone": "TSH",
    "plt": "Platelet Count",
    "platelets": "Platelet Count",
    "platelet count": "Platelet Count",
    "wbc": "WBC",
    "tlc": "WBC",
    "total leukocyte count": "WBC",
    "creatinine": "Serum Creatinine",
    "serum creatinine": "Serum Creatinine",
}

_UNIT_ALIASES: dict[str, str] = {
    "g/dl": "g/dL",
    "gm/dl": "g/dL",
    "g/dL": "g/dL",
    "mg/dl": "mg/dL",
    "mg/dL": "mg/dL",
    "mmol/l": "mmol/L",
    "/ul": "/uL",
    "/µl": "/uL",
    "cells/ul": "/uL",
    "/cumm": "/uL",
    "miu/l": "mIU/L",
    "uiu/ml": "mIU/L",
    "%": "%",
}

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%Y/%m/%d",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d %b %Y",
    "%d %B %Y",
)


def normalize_biomarker_name(name: str) -> str:
    """Normalize common biomarker aliases while preserving readable canonical names."""
    cleaned = " ".join(name.strip().split())
    return _BIOMARKER_ALIASES.get(cleaned.lower(), cleaned)


def normalize_unit(unit: Optional[str]) -> Optional[str]:
    """Normalize unit casing/spelling for safe comparability checks without converting values."""
    if not unit or not unit.strip():
        return None
    cleaned = " ".join(unit.strip().split())
    return _UNIT_ALIASES.get(cleaned.lower(), cleaned)


def parse_valid_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse a date string into a datetime object, returning None if missing or invalid."""
    if not date_str or not date_str.strip():
        return None
    cleaned = " ".join(date_str.strip().split())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None


def _parse_date_sort_key(date_str: Optional[str]) -> tuple[int, str]:
    """Sort valid dated observations chronologically and place missing/invalid dates last."""
    dt = parse_valid_date(date_str)
    if dt is not None:
        return (0, dt.strftime("%Y-%m-%d"))
    return (1, "9999-99-99")


def _safe_source_ref(raw_ref: object, default_doc_id: Optional[str]) -> Optional[SourceReference]:
    if not isinstance(raw_ref, dict):
        return None
    try:
        ref = SourceReference.model_validate(raw_ref)
        if ref.document_id is None and default_doc_id:
            return ref.model_copy(update={"document_id": default_doc_id})
        return ref
    except Exception:
        return None


def reconcile_biomarkers(
    records: list[VerifiedRecordInput],
) -> tuple[list[BiomarkerTrend], list[CrossDocumentConflict], list[FieldUncertainty]]:
    """Aggregate and analyze longitudinal biomarker trends across verified records."""
    grouped: dict[str, list[BiomarkerDataPoint]] = defaultdict(list)

    for rec in records:
        for b in rec.biomarkers:
            if not isinstance(b, dict):
                continue
            raw_name = str(b.get("name") or "").strip()
            raw_value = b.get("value")
            if not raw_name or raw_value is None:
                continue

            canonical_name = normalize_biomarker_name(raw_name)
            numeric_val = b.get("numeric_value")
            if numeric_val is None:
                try:
                    numeric_val = float(str(raw_value).strip())
                except (ValueError, TypeError):
                    numeric_val = None

            grouped[canonical_name].append(
                BiomarkerDataPoint(
                    document_id=rec.document_id,
                    recorded_date=rec.document_date,
                    value=str(raw_value),
                    numeric_value=numeric_val,
                    unit=b.get("unit"),
                    reference_range=b.get("reference_range"),
                    abnormal_flag=b.get("abnormal_flag"),
                    source_reference=_safe_source_ref(b.get("source_reference"), rec.document_id),
                )
            )

    trends: list[BiomarkerTrend] = []
    conflicts: list[CrossDocumentConflict] = []
    uncertainties: list[FieldUncertainty] = []

    for name in sorted(grouped.keys()):
        points = sorted(grouped[name], key=lambda p: _parse_date_sort_key(p.recorded_date))
        norm_units = {normalize_unit(p.unit) for p in points if normalize_unit(p.unit) is not None}
        has_missing_unit = any(normalize_unit(p.unit) is None for p in points)

        # Reject comparison if incompatible units exist
        if len(norm_units) > 1:
            doc_ids = sorted({p.document_id for p in points if p.document_id})
            refs = [p.source_reference for p in points if p.source_reference is not None]
            conflicts.append(
                CrossDocumentConflict(
                    conflict_type="biomarker_unit_mismatch",
                    field_name=name,
                    severity=ConflictSeverity.MEDIUM,
                    description=(
                        f"Incompatible units recorded for '{name}' ({sorted(norm_units)}); "
                        "values cannot be compared without verified conversion."
                    ),
                    document_ids=doc_ids,
                    source_references=refs,
                )
            )
            uncertainties.append(
                FieldUncertainty(
                    field_name=name,
                    reason=f"Mixed units ({', '.join(sorted(norm_units))}) prevent reliable trend calculation.",
                )
            )
            trends.append(
                BiomarkerTrend(
                    biomarker_name=name,
                    normalized_unit=None,
                    trend_direction=TrendDirection.INSUFFICIENT_DATA,
                    is_comparable=False,
                    data_points=points,
                    summary_note=f"{name}: {len(points)} records found with incompatible units; trend not computed.",
                )
            )
            continue

        # Reject comparison if some records have a unit and others are missing a unit
        if len(norm_units) == 1 and has_missing_unit and len(points) > 1:
            canonical_unit = next(iter(norm_units))
            uncertainties.append(
                FieldUncertainty(
                    field_name=name,
                    reason=(
                        f"One or more '{name}' records are missing a unit while others specify "
                        f"'{canonical_unit}'; values cannot be safely compared."
                    ),
                )
            )
            trends.append(
                BiomarkerTrend(
                    biomarker_name=name,
                    normalized_unit=canonical_unit,
                    trend_direction=TrendDirection.INSUFFICIENT_DATA,
                    is_comparable=False,
                    data_points=points,
                    summary_note=f"{name}: missing unit on one or more records prevents safe trend comparison.",
                )
            )
            continue

        canonical_unit = next(iter(norm_units), None)

        # Check same-date conflicting numeric values (only on valid dates)
        by_date: dict[str, list[BiomarkerDataPoint]] = defaultdict(list)
        for p in points:
            dt = parse_valid_date(p.recorded_date)
            if dt is not None and p.numeric_value is not None:
                by_date[dt.strftime("%Y-%m-%d")].append(p)

        has_same_date_conflict = False
        for date_key, same_day_points in by_date.items():
            vals = {round(p.numeric_value, 4) for p in same_day_points if p.numeric_value is not None}
            if len(vals) > 1:
                has_same_date_conflict = True
                doc_ids = sorted({p.document_id for p in same_day_points if p.document_id})
                refs = [p.source_reference for p in same_day_points if p.source_reference is not None]
                conflicts.append(
                    CrossDocumentConflict(
                        conflict_type="biomarker_same_date_mismatch",
                        field_name=name,
                        severity=ConflictSeverity.HIGH,
                        description=(
                            f"Conflicting values recorded for '{name}' on {date_key}: "
                            f"{[p.value for p in same_day_points]}."
                        ),
                        document_ids=doc_ids,
                        source_references=refs,
                    )
                )

        if has_same_date_conflict:
            uncertainties.append(
                FieldUncertainty(
                    field_name=name,
                    reason=f"Conflicting same-date values for '{name}' prevent reliable trend direction.",
                )
            )
            trends.append(
                BiomarkerTrend(
                    biomarker_name=name,
                    normalized_unit=canonical_unit,
                    trend_direction=TrendDirection.INSUFFICIENT_DATA,
                    is_comparable=False,
                    data_points=points,
                    summary_note=f"{name}: conflicting same-date values detected; trend withheld pending review.",
                )
            )
            continue

        # Compute longitudinal trend only from valid-dated numeric points
        dated_numeric = [
            p for p in points
            if parse_valid_date(p.recorded_date) is not None and p.numeric_value is not None
        ]

        if len(dated_numeric) < 2:
            trends.append(
                BiomarkerTrend(
                    biomarker_name=name,
                    normalized_unit=canonical_unit,
                    trend_direction=TrendDirection.INSUFFICIENT_DATA,
                    is_comparable=False,
                    data_points=points,
                    summary_note=(
                        f"{name}: {len(points)} observation(s) recorded; "
                        "at least 2 validly dated numeric values are required for a trend."
                    ),
                )
            )
            continue

        # Compute deltas across consecutive dated points
        deltas = [
            dated_numeric[i + 1].numeric_value - dated_numeric[i].numeric_value
            for i in range(len(dated_numeric) - 1)
        ]
        baseline = abs(dated_numeric[0].numeric_value) or 1.0
        tolerance = max(0.01, 0.02 * baseline)

        significant_pos = any(d > tolerance for d in deltas)
        significant_neg = any(d < -tolerance for d in deltas)

        if significant_pos and significant_neg:
            direction = TrendDirection.FLUCTUATING
        elif significant_pos:
            direction = TrendDirection.INCREASING
        elif significant_neg:
            direction = TrendDirection.DECREASING
        else:
            direction = TrendDirection.STABLE

        first, last = dated_numeric[0], dated_numeric[-1]
        unit_suffix = f" {canonical_unit}" if canonical_unit else ""
        trends.append(
            BiomarkerTrend(
                biomarker_name=name,
                normalized_unit=canonical_unit,
                trend_direction=direction,
                is_comparable=True,
                data_points=points,
                summary_note=(
                    f"{name} is {direction.value} across {len(dated_numeric)} dated records "
                    f"({first.value}{unit_suffix} on {first.recorded_date} -> "
                    f"{last.value}{unit_suffix} on {last.recorded_date})."
                ),
            )
        )

    return trends, conflicts, uncertainties
