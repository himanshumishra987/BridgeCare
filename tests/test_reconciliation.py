"""Automated tests for Cross-Document Medical Intelligence and Reconciliation."""

import pytest

from ai_engine.providers.exceptions import UnverifiedRecordError
from ai_engine.reconciliation import CrossDocumentReconciler
from ai_engine.schemas.common import VerificationStatus
from ai_engine.schemas.reconciliation import (
    ConflictSeverity,
    MedicationReconciliationStatus,
    ReconciliationResult,
    TrendDirection,
)


def _verified_lab(doc_id: str, date: str | None, biomarkers: list[dict], status: str = "verified", patient: str | None = None) -> dict:
    return {
        "document_id": doc_id,
        "verification_status": status,
        "document_type": "lab_report",
        "document_date": date,
        "hospital_or_lab_name": "Synthetic Lab",
        "patient_name": patient,
        "biomarkers": biomarkers,
        "medications": [],
        "clinical_events": [],
    }


def _verified_rx(doc_id: str, date: str | None, medications: list[dict], status: str = "verified") -> dict:
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


# =============================================================================
# 1. Human-Verification Gate & Empty Inputs
# =============================================================================


def test_reconciler_rejects_unverified_and_rejected_records():
    reconciler = CrossDocumentReconciler()

    with pytest.raises(UnverifiedRecordError):
        reconciler.reconcile([_verified_lab("d1", "2026-01-01", [], status=VerificationStatus.PENDING_REVIEW.value)])

    with pytest.raises(UnverifiedRecordError):
        reconciler.reconcile([_verified_lab("d1", "2026-01-01", [], status=VerificationStatus.REJECTED.value)])

    unlabeled = _verified_lab("d1", "2026-01-01", [])
    del unlabeled["verification_status"]
    with pytest.raises(UnverifiedRecordError):
        reconciler.reconcile([unlabeled])


def test_reconciler_empty_records_returns_insufficient_data():
    reconciler = CrossDocumentReconciler()
    res = reconciler.reconcile([])
    assert isinstance(res, ReconciliationResult)
    assert res.insufficient_data is True
    assert res.is_clinically_verified is False
    assert len(res.uncertainty_flags) == 1


# =============================================================================
# 2. Biomarker Normalization, Trends & Unit Safety
# =============================================================================


def test_reconcile_biomarker_trends_and_aliases():
    reconciler = CrossDocumentReconciler()
    records = [
        _verified_lab(
            "d1",
            "2026-01-10",
            [
                {"name": "Hb", "value": "11.0", "numeric_value": 11.0, "unit": "g/dl"},
                {"name": "Fasting Glucose", "value": "140", "numeric_value": 140.0, "unit": "mg/dL"},
            ],
            status="verified",
        ),
        _verified_lab(
            "d2",
            "2026-02-10",
            [
                {"name": "Hemoglobin", "value": "12.5", "numeric_value": 12.5, "unit": "g/dL"},
                {"name": "FBS", "value": "120", "numeric_value": 120.0, "unit": "mg/dL"},
            ],
            status="edited_verified",
        ),
        _verified_lab(
            "d3",
            "2026-03-10",
            [
                {"name": "Haemoglobin", "value": "13.8", "numeric_value": 13.8, "unit": "gm/dl"},
                {"name": "Fasting Blood Sugar", "value": "105", "numeric_value": 105.0, "unit": "mg/dl"},
            ],
            status="verified",
        ),
    ]

    res = reconciler.reconcile(records)
    assert res.insufficient_data is False
    assert res.is_clinically_verified is False
    assert res.source_record_ids == ["d1", "d2", "d3"]

    by_name = {t.biomarker_name: t for t in res.biomarker_trends}
    assert by_name["Hemoglobin"].trend_direction == TrendDirection.INCREASING
    assert by_name["Hemoglobin"].is_comparable is True
    assert by_name["Hemoglobin"].normalized_unit == "g/dL"

    assert by_name["Fasting Glucose"].trend_direction == TrendDirection.DECREASING
    assert by_name["Fasting Glucose"].is_comparable is True
    assert by_name["Fasting Glucose"].normalized_unit == "mg/dL"


def test_reconcile_biomarker_incompatible_units_flagged_not_converted():
    reconciler = CrossDocumentReconciler()
    records = [
        _verified_lab("d1", "2026-01-01", [{"name": "Glucose", "value": "110", "numeric_value": 110.0, "unit": "mg/dL"}]),
        _verified_lab("d2", "2026-02-01", [{"name": "Glucose", "value": "6.1", "numeric_value": 6.1, "unit": "mmol/L"}]),
    ]

    res = reconciler.reconcile(records)
    trend = res.biomarker_trends[0]
    assert trend.is_comparable is False
    assert trend.trend_direction == TrendDirection.INSUFFICIENT_DATA
    assert any(c.conflict_type == "biomarker_unit_mismatch" for c in res.conflicts)
    assert any(u.field_name == "Glucose" for u in res.uncertainty_flags)


def test_reconcile_biomarker_same_date_conflict_detected():
    reconciler = CrossDocumentReconciler()
    records = [
        _verified_lab("d1", "2026-03-01", [{"name": "TSH", "value": "4.8", "numeric_value": 4.8, "unit": "mIU/L"}]),
        _verified_lab("d2", "2026-03-01", [{"name": "TSH", "value": "2.1", "numeric_value": 2.1, "unit": "mIU/L"}]),
    ]

    res = reconciler.reconcile(records)
    same_day = [c for c in res.conflicts if c.conflict_type == "biomarker_same_date_mismatch"]
    assert len(same_day) == 1
    assert same_day[0].severity == ConflictSeverity.HIGH
    assert same_day[0].document_ids == ["d1", "d2"]


# =============================================================================
# 3. Medication Reconciliation & Conflict Detection
# =============================================================================


def test_reconcile_medications_dose_change_duplicate_and_conflict():
    reconciler = CrossDocumentReconciler()
    records = [
        # Dose changed across dates for Metformin
        _verified_rx(
            "rx1",
            "2026-01-05",
            [
                {
                    "brand_name": "GlucoSyn",
                    "generic_ingredients": ["Metformin"],
                    "strength": "500 mg",
                    "dosage": "1 tablet",
                    "frequency": "Once daily",
                }
            ],
        ),
        _verified_rx(
            "rx2",
            "2026-02-05",
            [
                {
                    "brand_name": "GlucoSyn",
                    "generic_ingredients": ["Metformin"],
                    "strength": "500 mg",
                    "dosage": "1 tablet",
                    "frequency": "Twice daily",
                }
            ],
        ),
        # Duplicate active ingredient across two distinct brands for Atorvastatin
        _verified_rx(
            "rx3",
            "2026-02-05",
            [
                {
                    "brand_name": "LipidBrandA",
                    "generic_ingredients": ["Atorvastatin"],
                    "strength": "10 mg",
                    "dosage": "1 tablet",
                    "frequency": "Nightly",
                }
            ],
        ),
        _verified_rx(
            "rx4",
            "2026-02-15",
            [
                {
                    "brand_name": "LipidBrandB",
                    "generic_ingredients": ["Atorvastatin"],
                    "strength": "10 mg",
                    "dosage": "1 tablet",
                    "frequency": "Nightly",
                }
            ],
        ),
    ]

    res = reconciler.reconcile(records)
    by_med = {m.medication_key: m for m in res.reconciled_medications}

    assert by_med["metformin"].status == MedicationReconciliationStatus.DOSE_OR_FREQUENCY_CHANGED
    assert by_med["atorvastatin"].status == MedicationReconciliationStatus.DUPLICATE_INGREDIENT
    assert any(c.conflict_type == "duplicate_active_ingredient" for c in res.conflicts)


def test_reconcile_same_date_medication_conflict():
    reconciler = CrossDocumentReconciler()
    records = [
        _verified_rx(
            "rx1",
            "2026-04-01",
            [{"brand_name": "SynMed", "generic_ingredients": ["Ibuprofen"], "strength": "200 mg", "frequency": "Twice daily"}],
        ),
        _verified_rx(
            "rx2",
            "2026-04-01",
            [{"brand_name": "SynMed", "generic_ingredients": ["Ibuprofen"], "strength": "400 mg", "frequency": "Three times daily"}],
        ),
    ]

    res = reconciler.reconcile(records)
    assert res.reconciled_medications[0].status == MedicationReconciliationStatus.CONFLICTING
    assert any(c.conflict_type == "medication_regimen_conflict" for c in res.conflicts)


# =============================================================================
# 4. Chronological Timeline & Metadata Conflicts
# =============================================================================


def test_reconcile_chronological_timeline_and_metadata_mismatch():
    reconciler = CrossDocumentReconciler()
    records = [
        {
            "document_id": "doc-later",
            "verification_status": "verified",
            "document_type": "discharge_summary",
            "document_date": "2026-03-15",
            "patient_name": "Synthetic Patient Alpha",
            "clinical_events": [
                {"event_type": "discharge", "description": "Discharged stable.", "event_date": "2026-03-15"}
            ],
        },
        {
            "document_id": "doc-undated",
            "verification_status": "verified",
            "document_type": "clinical_note",
            "document_date": None,
            "clinical_events": [
                {"event_type": "symptom", "description": "Undated symptom note.", "event_date": None}
            ],
        },
        {
            "document_id": "doc-earlier",
            "verification_status": "verified",
            "document_type": "lab_report",
            "document_date": "2026-01-10",
            "patient_name": "Synthetic Patient Beta",
            "biomarkers": [{"name": "WBC", "value": "7000", "numeric_value": 7000.0, "unit": "/uL"}],
            "clinical_events": [],
        },
    ]

    res = reconciler.reconcile(records)
    assert [e.document_id for e in res.timeline] == ["doc-earlier", "doc-later", "doc-undated"]
    assert res.timeline[0].date_missing is False
    assert res.timeline[2].date_missing is True
    assert any(c.conflict_type == "patient_metadata_mismatch" for c in res.conflicts)


def test_reconcile_missing_unit_not_silently_compared():
    reconciler = CrossDocumentReconciler()
    records = [
        _verified_lab("d1", "2026-01-01", [{"name": "Glucose", "value": "110", "numeric_value": 110.0, "unit": "mg/dL"}]),
        _verified_lab("d2", "2026-02-01", [{"name": "Glucose", "value": "6.1", "numeric_value": 6.1, "unit": None}]),
    ]

    res = reconciler.reconcile(records)
    trend = res.biomarker_trends[0]
    assert trend.is_comparable is False
    assert trend.trend_direction == TrendDirection.INSUFFICIENT_DATA
    assert any("missing a unit" in u.reason for u in res.uncertainty_flags)


def test_reconcile_invalid_dates_in_biomarkers_and_timeline():
    reconciler = CrossDocumentReconciler()
    records = [
        _verified_lab("d-invalid", "not-a-real-date", [{"name": "Hemoglobin", "value": "13.0", "numeric_value": 13.0, "unit": "g/dL"}]),
        _verified_lab("d-valid", "2026-01-15", [{"name": "Hemoglobin", "value": "13.5", "numeric_value": 13.5, "unit": "g/dL"}]),
    ]

    res = reconciler.reconcile(records)
    # Only 1 valid date -> cannot compute longitudinal trend
    assert res.biomarker_trends[0].trend_direction == TrendDirection.INSUFFICIENT_DATA
    assert res.biomarker_trends[0].is_comparable is False
    # Timeline places valid date first and invalid date last with date_missing=True
    assert [e.document_id for e in res.timeline] == ["d-valid", "d-invalid"]
    assert res.timeline[0].date_missing is False
    assert res.timeline[1].date_missing is True


def test_reconcile_brand_matches_known_generic_and_missing_dosage_not_flagged_as_change():
    reconciler = CrossDocumentReconciler()
    records = [
        _verified_rx(
            "rx1",
            "2026-01-10",
            [{"brand_name": "GlucoSyn", "generic_ingredients": ["Metformin"], "strength": "500 mg", "dosage": "1 tablet", "frequency": "Twice daily"}],
        ),
        _verified_rx(
            "rx2",
            "2026-02-10",
            [{"brand_name": "GlucoSyn", "generic_ingredients": [], "strength": "500 mg", "dosage": None, "frequency": None}],
        ),
    ]

    res = reconciler.reconcile(records)
    assert len(res.reconciled_medications) == 1
    med = res.reconciled_medications[0]
    assert med.medication_key == "metformin"
    assert med.status == MedicationReconciliationStatus.CONSISTENT
    assert any("missing" in n.lower() for n in med.notes)
