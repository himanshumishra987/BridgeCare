"""Biomarker pattern identification: reference-range deviations, rapid changes, and relationships."""

from typing import Optional

from ai_engine.patterns.reference_range import classify_point_status
from ai_engine.reconciliation.biomarkers import parse_valid_date
from ai_engine.schemas.common import (
    ConfidenceCategory,
    ConfidenceScore,
    FieldUncertainty,
    SourceReference,
)
from ai_engine.schemas.patterns import (
    HealthPattern,
    PatternCategory,
    PatternSeverity,
)
from ai_engine.schemas.reconciliation import (
    BiomarkerDataPoint,
    BiomarkerTrend,
    TrendDirection,
)

_SOURCE = "bridgecare:pattern_analyzer"
_MEANINGFUL_PCT_THRESHOLD = 15.0
_RAPID_PCT_THRESHOLD = 20.0
_RAPID_DAYS_WINDOW = 30


def _collect_refs(points: list[BiomarkerDataPoint]) -> list[SourceReference]:
    return [p.source_reference for p in points if p.source_reference is not None]


def _slug(name: str) -> str:
    return "_".join(name.lower().split())


def identify_biomarker_patterns(
    trends: list[BiomarkerTrend],
) -> tuple[list[HealthPattern], list[FieldUncertainty]]:
    """Identify reference-range, repeated abnormal, rapid-change, and relationship patterns."""
    patterns: list[HealthPattern] = []
    uncertainties: list[FieldUncertainty] = []

    # Map canonical name -> (trend, latest_comparable_point, latest_status)
    latest_info: dict[str, tuple[BiomarkerTrend, BiomarkerDataPoint, Optional[str]]] = {}

    for trend in trends:
        if not trend.data_points:
            continue

        # Skip longitudinal patterns when units/conflicts make the trend non-comparable
        if len(trend.data_points) > 1 and not trend.is_comparable:
            uncertainties.append(
                FieldUncertainty(
                    field_name=trend.biomarker_name,
                    reason=(
                        f"Skipped longitudinal pattern identification for '{trend.biomarker_name}' "
                        "because records are not safely comparable (unit mismatch, missing unit, or same-date conflict)."
                    ),
                )
            )
            continue

        # Evaluate point statuses
        point_statuses: list[tuple[BiomarkerDataPoint, Optional[str]]] = []
        for p in trend.data_points:
            status, _ = classify_point_status(p)
            point_statuses.append((p, status))

        latest_pt, latest_status = point_statuses[-1]
        latest_info[trend.biomarker_name] = (trend, latest_pt, latest_status)

        # 1. Repeated abnormal observation detection (>= 2 abnormal observations)
        abnormal_pts = [
            (p, st) for p, st in point_statuses
            if st in ("high", "low", "abnormal")
        ]
        if len(abnormal_pts) >= 2:
            directions = {st for _, st in abnormal_pts}
            dir_desc = next(iter(directions)) if len(directions) == 1 else "out-of-range"
            unit_str = f" {trend.normalized_unit}" if trend.normalized_unit else ""
            values_summary = ", ".join(
                f"{p.value}{unit_str} ({p.recorded_date or 'undated'})"
                for p, _ in abnormal_pts
            )
            patterns.append(
                HealthPattern(
                    pattern_id=f"repeated_abnormal_{_slug(trend.biomarker_name)}",
                    category=PatternCategory.REPEATED_ABNORMALITY,
                    title=f"Repeated {dir_desc} {trend.biomarker_name} observations",
                    severity=PatternSeverity.HIGH,
                    explanation=(
                        f"Observed {len(abnormal_pts)} {dir_desc} {trend.biomarker_name} values "
                        f"across verified records: {values_summary}. "
                        "This is an observational flag for clinician review, not a diagnosis."
                    ),
                    related_biomarkers=[trend.biomarker_name],
                    confidence=ConfidenceScore(
                        score=0.92,
                        source=_SOURCE,
                        category=ConfidenceCategory.HIGH,
                    ),
                    source_references=_collect_refs([p for p, _ in abnormal_pts]),
                )
            )
        elif latest_status in ("high", "low", "abnormal"):
            # 2. Single / latest reference-range deviation
            unit_str = f" {latest_pt.unit}" if latest_pt.unit else ""
            range_note = f" (documented reference range: {latest_pt.reference_range})" if latest_pt.reference_range else ""
            patterns.append(
                HealthPattern(
                    pattern_id=f"ref_deviation_{_slug(trend.biomarker_name)}",
                    category=PatternCategory.REFERENCE_RANGE_DEVIATION,
                    title=f"{trend.biomarker_name} outside documented reference range ({latest_status})",
                    severity=PatternSeverity.MEDIUM,
                    explanation=(
                        f"Observed {trend.biomarker_name} value of {latest_pt.value}{unit_str} "
                        f"on {latest_pt.recorded_date or 'undated record'} is {latest_status}{range_note}. "
                        "An isolated out-of-range value is not a clinical diagnosis."
                    ),
                    related_biomarkers=[trend.biomarker_name],
                    confidence=ConfidenceScore(
                        score=0.9,
                        source=_SOURCE,
                        category=ConfidenceCategory.HIGH,
                    ),
                    source_references=_collect_refs([latest_pt]),
                )
            )

        # 3. Meaningful longitudinal & rapid-change flags (using valid dated comparable points)
        dated_pts = [
            p for p in trend.data_points
            if parse_valid_date(p.recorded_date) is not None and p.numeric_value is not None
        ]
        if trend.is_comparable and len(dated_pts) >= 2:
            rapid_detected = False
            for i in range(len(dated_pts) - 1):
                p1, p2 = dated_pts[i], dated_pts[i + 1]
                dt1 = parse_valid_date(p1.recorded_date)
                dt2 = parse_valid_date(p2.recorded_date)
                assert dt1 is not None and dt2 is not None
                days = (dt2 - dt1).days
                if days <= 0 or p1.numeric_value == 0:
                    continue
                pct = ((p2.numeric_value - p1.numeric_value) / abs(p1.numeric_value)) * 100.0
                if abs(pct) >= _RAPID_PCT_THRESHOLD and days <= _RAPID_DAYS_WINDOW:
                    rapid_detected = True
                    unit_str = f" {trend.normalized_unit}" if trend.normalized_unit else ""
                    patterns.append(
                        HealthPattern(
                            pattern_id=f"rapid_change_{_slug(trend.biomarker_name)}_{i}",
                            category=PatternCategory.RAPID_OR_MEANINGFUL_CHANGE,
                            title=f"Rapid change in {trend.biomarker_name} within {days} day(s)",
                            severity=PatternSeverity.HIGH,
                            explanation=(
                                f"Observed {pct:+.1f}% change in {trend.biomarker_name} "
                                f"({p1.value}{unit_str} on {p1.recorded_date} -> "
                                f"{p2.value}{unit_str} on {p2.recorded_date}, {days} days apart). "
                                "Warrants clinician review."
                            ),
                            related_biomarkers=[trend.biomarker_name],
                            confidence=ConfidenceScore(
                                score=0.9,
                                source=_SOURCE,
                                category=ConfidenceCategory.HIGH,
                            ),
                            source_references=_collect_refs([p1, p2]),
                        )
                    )

            if not rapid_detected and trend.trend_direction in (
                TrendDirection.INCREASING,
                TrendDirection.DECREASING,
                TrendDirection.FLUCTUATING,
            ):
                first, last = dated_pts[0], dated_pts[-1]
                if first.numeric_value != 0:
                    overall_pct = ((last.numeric_value - first.numeric_value) / abs(first.numeric_value)) * 100.0
                    if abs(overall_pct) >= _MEANINGFUL_PCT_THRESHOLD:
                        unit_str = f" {trend.normalized_unit}" if trend.normalized_unit else ""
                        patterns.append(
                            HealthPattern(
                                pattern_id=f"meaningful_change_{_slug(trend.biomarker_name)}",
                                category=PatternCategory.RAPID_OR_MEANINGFUL_CHANGE,
                                title=f"Meaningful {trend.trend_direction.value} shift in {trend.biomarker_name}",
                                severity=PatternSeverity.MEDIUM,
                                explanation=(
                                    f"Observed {overall_pct:+.1f}% overall {trend.trend_direction.value} change "
                                    f"in {trend.biomarker_name} ({first.value}{unit_str} on {first.recorded_date} -> "
                                    f"{last.value}{unit_str} on {last.recorded_date})."
                                ),
                                related_biomarkers=[trend.biomarker_name],
                                confidence=ConfidenceScore(
                                    score=0.88,
                                    source=_SOURCE,
                                    category=ConfidenceCategory.HIGH,
                                ),
                                source_references=_collect_refs([first, last]),
                            )
                        )

    # 4. Carefully defined relationships between compatible biomarkers
    patterns.extend(_identify_biomarker_relationships(latest_info))

    return patterns, uncertainties


def _identify_biomarker_relationships(
    latest_info: dict[str, tuple[BiomarkerTrend, BiomarkerDataPoint, Optional[str]]],
) -> list[HealthPattern]:
    """Identify documented concurrent patterns across compatible biomarker pairs."""
    rel_patterns: list[HealthPattern] = []

    # Glycemic markers: Fasting Glucose + HbA1c
    if "Fasting Glucose" in latest_info and "HbA1c" in latest_info:
        _, g_pt, g_st = latest_info["Fasting Glucose"]
        _, a_pt, a_st = latest_info["HbA1c"]
        if g_st == "high" and a_st == "high":
            rel_patterns.append(
                HealthPattern(
                    pattern_id="rel_glycemic_concurrent_elevation",
                    category=PatternCategory.BIOMARKER_RELATIONSHIP,
                    title="Concurrent elevation in Fasting Glucose and HbA1c",
                    severity=PatternSeverity.HIGH,
                    explanation=(
                        f"Both Fasting Glucose ({g_pt.value} {g_pt.unit or ''}) and "
                        f"HbA1c ({a_pt.value} {a_pt.unit or ''}) are above documented reference ranges. "
                        "Observation only; requires clinician evaluation."
                    ),
                    related_biomarkers=["Fasting Glucose", "HbA1c"],
                    confidence=ConfidenceScore(
                        score=0.88,
                        source=_SOURCE,
                        category=ConfidenceCategory.HIGH,
                    ),
                    source_references=_collect_refs([g_pt, a_pt]),
                )
            )

    # Renal markers: Serum Creatinine + eGFR
    if "Serum Creatinine" in latest_info and "eGFR" in latest_info:
        c_tr, c_pt, c_st = latest_info["Serum Creatinine"]
        e_tr, e_pt, e_st = latest_info["eGFR"]
        creatinine_elevated = c_st == "high" or c_tr.trend_direction == TrendDirection.INCREASING
        egfr_reduced = e_st == "low" or e_tr.trend_direction == TrendDirection.DECREASING
        if creatinine_elevated and egfr_reduced:
            rel_patterns.append(
                HealthPattern(
                    pattern_id="rel_renal_creatinine_egfr",
                    category=PatternCategory.BIOMARKER_RELATIONSHIP,
                    title="Concurrent Serum Creatinine and eGFR shift",
                    severity=PatternSeverity.HIGH,
                    explanation=(
                        f"Observed Serum Creatinine ({c_pt.value} {c_pt.unit or ''}) alongside "
                        f"eGFR ({e_pt.value} {e_pt.unit or ''}). "
                        "Concurrent renal marker shifts warrant clinician review, not an automated diagnosis."
                    ),
                    related_biomarkers=["Serum Creatinine", "eGFR"],
                    confidence=ConfidenceScore(
                        score=0.86,
                        source=_SOURCE,
                        category=ConfidenceCategory.HIGH,
                    ),
                    source_references=_collect_refs([c_pt, e_pt]),
                )
            )

    # Hematology markers: Hemoglobin + Ferritin / MCV
    if "Hemoglobin" in latest_info:
        _, hb_pt, hb_st = latest_info["Hemoglobin"]
        if hb_st == "low":
            for partner in ("Ferritin", "MCV"):
                if partner in latest_info:
                    _, p_pt, p_st = latest_info[partner]
                    if p_st == "low":
                        rel_patterns.append(
                            HealthPattern(
                                pattern_id=f"rel_hematology_hb_{_slug(partner)}",
                                category=PatternCategory.BIOMARKER_RELATIONSHIP,
                                title=f"Concurrent low Hemoglobin and low {partner}",
                                severity=PatternSeverity.MEDIUM,
                                explanation=(
                                    f"Both Hemoglobin ({hb_pt.value} {hb_pt.unit or ''}) and "
                                    f"{partner} ({p_pt.value} {p_pt.unit or ''}) are below documented reference ranges. "
                                    "Observational finding for clinician review only."
                                ),
                                related_biomarkers=["Hemoglobin", partner],
                                confidence=ConfidenceScore(
                                    score=0.85,
                                    source=_SOURCE,
                                    category=ConfidenceCategory.HIGH,
                                ),
                                source_references=_collect_refs([hb_pt, p_pt]),
                            )
                        )

    # Lipid markers: >= 2 out-of-range among LDL, HDL, Triglycerides, Total Cholesterol
    lipid_abnormal: list[tuple[str, BiomarkerDataPoint, str]] = []
    for marker, expected_dir in (
        ("LDL", "high"),
        ("Total Cholesterol", "high"),
        ("Triglycerides", "high"),
        ("HDL", "low"),
    ):
        if marker in latest_info:
            _, pt, st = latest_info[marker]
            if st == expected_dir:
                lipid_abnormal.append((marker, pt, st))

    if len(lipid_abnormal) >= 2:
        names = [m for m, _, _ in lipid_abnormal]
        pts = [p for _, p, _ in lipid_abnormal]
        lipid_summary = ", ".join(
            f"{m}={p.value} {p.unit}".strip() if p.unit else f"{m}={p.value}"
            for m, p, _ in lipid_abnormal
        )
        rel_patterns.append(
            HealthPattern(
                pattern_id="rel_lipid_panel_concurrent",
                category=PatternCategory.BIOMARKER_RELATIONSHIP,
                title=f"Concurrent out-of-range lipid markers ({', '.join(names)})",
                severity=PatternSeverity.MEDIUM,
                explanation=(
                    f"Multiple lipid markers are outside documented reference ranges: "
                    f"{lipid_summary}. "
                    "Observation for clinician review."
                ),
                related_biomarkers=names,
                confidence=ConfidenceScore(
                    score=0.85,
                    source=_SOURCE,
                    category=ConfidenceCategory.HIGH,
                ),
                source_references=_collect_refs(pts),
            )
        )

    return rel_patterns
