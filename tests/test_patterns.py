"""Automated tests for Intelligent Health Pattern Identification."""

import pytest

from ai_engine.patterns import HealthPatternAnalyzer, parse_reference_range
from ai_engine.providers.exceptions import UnverifiedRecordError
from ai_engine.schemas.patterns import (
    PatternCategory,
    PatternIdentificationResult,
    PatternSeverity,
)


def _lab(doc_id: str, date: str | None, biomarkers: list[dict], status: str = "verified") -> dict:
    return {
        "document_id": doc_id,
        "verification_status": status,
        "document_type": "lab_report",
        "document_date": date,
        "hospital_or_lab_name": "Synthetic Lab",
        "biomarkers": biomarkers,
        "medications": [],
        "clinical_events": [],
    }


def _rx(doc_id: str, date: str | None, medications: list[dict], status: str = "verified") -> dict:
    return {
        "document_id": doc_id,
        "verification_status": status,
        "document_type": "prescription",
        "document_date": date,
        "hospital_or_lab_name": "Synthetic Clinic",
        "biomarkers": [],
        "medications": medications,
        "clinical_events": [],
    }


def test_parse_reference_range_formats():
    assert parse_reference_range("12.0-16.0") == (12.0, 16.0)
    assert parse_reference_range("70 - 100") == (70.0, 100.0)
    assert parse_reference_range("< 200") == (None, 200.0)
    assert parse_reference_range(">= 40") == (40.0, None)
    assert parse_reference_range("invalid") is None
    assert parse_reference_range(None) is None


def test_reference_range_deviation_and_observation_disclaimer():
    analyzer = HealthPatternAnalyzer()
    records = [
        _lab(
            "d1",
            "2026-02-01",
            [
                {
                    "name": "LDL",
                    "value": "165",
                    "numeric_value": 165.0,
                    "unit": "mg/dL",
                    "reference_range": "< 100",
                    "source_reference": {"document_id": "d1", "page_number": 1, "excerpt": "LDL: 165 mg/dL (< 100)"},
                }
            ],
        )
    ]

    res = analyzer.analyze_records(records)
    assert isinstance(res, PatternIdentificationResult)
    assert res.is_clinically_verified is False
    assert "Not a clinical diagnosis" in res.disclaimer
    assert len(res.patterns) == 1

    p = res.patterns[0]
    assert p.category == PatternCategory.REFERENCE_RANGE_DEVIATION
    assert p.severity == PatternSeverity.MEDIUM
    assert p.observation_only is True
    assert p.is_clinical_diagnosis is False
    assert len(p.source_references) == 1


def test_repeated_abnormal_observations_and_rapid_change():
    analyzer = HealthPatternAnalyzer()
    records = [
        _lab(
            "d1",
            "2026-01-01",
            [
                {
                    "name": "Fasting Glucose",
                    "value": "115",
                    "numeric_value": 115.0,
                    "unit": "mg/dL",
                    "reference_range": "70-100",
                    "source_reference": {"document_id": "d1", "page_number": 1, "excerpt": "FBS: 115 mg/dL"},
                }
            ],
        ),
        _lab(
            "d2",
            "2026-01-20",
            [
                {
                    "name": "Fasting Glucose",
                    "value": "155",
                    "numeric_value": 155.0,
                    "unit": "mg/dL",
                    "reference_range": "70-100",
                    "source_reference": {"document_id": "d2", "page_number": 1, "excerpt": "FBS: 155 mg/dL"},
                }
            ],
        ),
    ]

    res = analyzer.analyze_records(records)
    categories = {p.category for p in res.patterns}
    assert PatternCategory.REPEATED_ABNORMALITY in categories
    assert PatternCategory.RAPID_OR_MEANINGFUL_CHANGE in categories

    rapid = next(p for p in res.patterns if p.category == PatternCategory.RAPID_OR_MEANINGFUL_CHANGE)
    assert rapid.severity == PatternSeverity.HIGH
    assert "19 day(s)" in rapid.title
    assert len(rapid.source_references) == 2


def test_meaningful_longitudinal_change_over_irregular_longer_interval():
    analyzer = HealthPatternAnalyzer()
    records = [
        _lab("d1", "2025-06-01", [{"name": "Hemoglobin", "value": "14.5", "numeric_value": 14.5, "unit": "g/dL", "reference_range": "12.0-16.0"}]),
        _lab("d2", "2026-01-15", [{"name": "Hemoglobin", "value": "12.1", "numeric_value": 12.1, "unit": "g/dL", "reference_range": "12.0-16.0"}]),
    ]

    res = analyzer.analyze_records(records)
    assert len(res.patterns) == 1
    p = res.patterns[0]
    assert p.category == PatternCategory.RAPID_OR_MEANINGFUL_CHANGE
    assert p.severity == PatternSeverity.MEDIUM
    assert "Meaningful decreasing shift" in p.title


def test_biomarker_relationships_without_diagnosing():
    analyzer = HealthPatternAnalyzer()
    records = [
        _lab(
            "d1",
            "2026-03-01",
            [
                {"name": "Fasting Glucose", "value": "142", "numeric_value": 142.0, "unit": "mg/dL", "reference_range": "70-100"},
                {"name": "HbA1c", "value": "7.4", "numeric_value": 7.4, "unit": "%", "reference_range": "< 5.7"},
                {"name": "Hemoglobin", "value": "10.2", "numeric_value": 10.2, "unit": "g/dL", "reference_range": "12.0-16.0"},
                {"name": "Ferritin", "value": "9.0", "numeric_value": 9.0, "unit": "ng/mL", "reference_range": "15-150"},
            ],
        )
    ]

    res = analyzer.analyze_records(records)
    rel_patterns = [p for p in res.patterns if p.category == PatternCategory.BIOMARKER_RELATIONSHIP]
    assert len(rel_patterns) == 2
    for p in rel_patterns:
        assert p.is_clinical_diagnosis is False
        assert p.observation_only is True
        assert "diabetes" not in p.explanation.lower()
        assert "anemia" not in p.explanation.lower()


def test_medication_review_patterns():
    analyzer = HealthPatternAnalyzer()
    records = [
        _rx("rx1", "2026-01-01", [{"brand_name": "MedA", "generic_ingredients": ["Atorvastatin"], "strength": "10 mg", "dosage": "1 tab", "frequency": "Nightly"}]),
        _rx("rx2", "2026-02-01", [{"brand_name": "MedB", "generic_ingredients": ["Atorvastatin"], "strength": "10 mg", "dosage": None, "frequency": None}]),
        _rx("rx3", "2026-03-01", [{"brand_name": "PainX", "generic_ingredients": ["Ibuprofen"], "strength": "200 mg", "dosage": "1 tab", "frequency": "BID"}]),
        _rx("rx4", "2026-03-01", [{"brand_name": "PainX", "generic_ingredients": ["Ibuprofen"], "strength": "400 mg", "dosage": "1 tab", "frequency": "TID"}]),
    ]

    res = analyzer.analyze_records(records)
    med_patterns = [p for p in res.patterns if p.category == PatternCategory.MEDICATION_REVIEW]
    ids = {p.pattern_id for p in med_patterns}
    assert "med_duplicate_atorvastatin" in ids
    assert "med_incomplete_regimen_atorvastatin" in ids
    assert "med_conflict_ibuprofen" in ids


def test_false_positive_prevention_normal_fluctuations_and_missing_ranges():
    analyzer = HealthPatternAnalyzer()
    records = [
        _lab("d1", "2026-01-01", [{"name": "Hemoglobin", "value": "13.8", "numeric_value": 13.8, "unit": "g/dL", "reference_range": "12.0-16.0"}]),
        _lab("d2", "2026-01-10", [{"name": "Hemoglobin", "value": "14.1", "numeric_value": 14.1, "unit": "g/dL", "reference_range": "12.0-16.0"}]),
        _lab("d3", "2026-01-10", [{"name": "CustomMarker", "value": "50", "numeric_value": 50.0, "unit": "U/L"}]),
    ]

    res = analyzer.analyze_records(records)
    assert res.insufficient_data is False
    assert res.patterns == []


def test_incompatible_units_and_conflicting_records_prevent_false_patterns():
    analyzer = HealthPatternAnalyzer()
    records = [
        # Incompatible units
        _lab("d1", "2026-01-01", [{"name": "Glucose", "value": "110", "numeric_value": 110.0, "unit": "mg/dL", "reference_range": "70-100"}]),
        _lab("d2", "2026-01-05", [{"name": "Glucose", "value": "6.1", "numeric_value": 6.1, "unit": "mmol/L", "reference_range": "3.9-5.6"}]),
        # Same-date conflicting values
        _lab("d3", "2026-02-01", [{"name": "TSH", "value": "4.8", "numeric_value": 4.8, "unit": "mIU/L"}]),
        _lab("d4", "2026-02-01", [{"name": "TSH", "value": "2.1", "numeric_value": 2.1, "unit": "mIU/L"}]),
    ]

    res = analyzer.analyze_records(records)
    # Neither Glucose nor TSH should produce a false rapid-change or repeated-abnormality pattern
    assert res.patterns == []
    assert any(u.field_name == "Glucose" for u in res.uncertainty_flags)
    assert any(u.field_name == "TSH" for u in res.uncertainty_flags)


def test_insufficient_data_and_unverified_records_rejected():
    analyzer = HealthPatternAnalyzer()

    empty_res = analyzer.analyze_records([])
    assert empty_res.insufficient_data is True
    assert empty_res.patterns == []

    with pytest.raises(UnverifiedRecordError):
        analyzer.analyze_records(
            [_lab("d1", "2026-01-01", [{"name": "Hemoglobin", "value": "10.0"}], status="pending_review")]
        )
