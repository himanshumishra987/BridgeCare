"""Automated tests for the Intelligent Longitudinal Health Timeline."""

import pytest

from ai_engine.providers.exceptions import UnverifiedRecordError
from ai_engine.schemas.common import VerificationStatus
from ai_engine.schemas.longitudinal_timeline import LongitudinalTimelineResult
from ai_engine.timeline import LongitudinalTimelineBuilder


def test_timeline_connects_related_labs_consultations_and_before_after():
    """Test connecting related labs + consultations, chronological ordering, and before/after comparisons."""
    builder = LongitudinalTimelineBuilder(episode_window_days=5)
    # Intentionally supply records out of chronological order
    records = [
        {
            "document_id": "lab-after",
            "verification_status": "verified",
            "document_type": "lab_report",
            "document_date": "2026-03-10",
            "biomarkers": [
                {
                    "name": "Fasting Glucose",
                    "value": "102",
                    "numeric_value": 102.0,
                    "unit": "mg/dL",
                    "reference_range": "70-100",
                    "source_reference": {"document_id": "lab-after", "page_number": 1, "excerpt": "FBS: 102 mg/dL"},
                }
            ],
            "clinical_events": [],
        },
        {
            "document_id": "consult-mid",
            "verification_status": "edited_verified",
            "document_type": "clinical_note",
            "document_date": "2026-02-01",
            "clinical_events": [
                {
                    "event_type": "consultation",
                    "description": "Outpatient follow-up consultation.",
                    "event_date": "2026-02-01",
                    "source_reference": {"document_id": "consult-mid", "page_number": 1, "excerpt": "Outpatient follow-up consultation."},
                }
            ],
        },
        {
            "document_id": "lab-before",
            "verification_status": "verified",
            "document_type": "lab_report",
            "document_date": "2026-01-10",
            "biomarkers": [
                {
                    "name": "Fasting Glucose",
                    "value": "145",
                    "numeric_value": 145.0,
                    "unit": "mg/dL",
                    "reference_range": "70-100",
                    "source_reference": {"document_id": "lab-before", "page_number": 1, "excerpt": "FBS: 145 mg/dL"},
                }
            ],
            "clinical_events": [],
        },
        {
            "document_id": "consult-jan",
            "verification_status": "verified",
            "document_type": "clinical_note",
            "document_date": "2026-01-12",
            "clinical_events": [
                {
                    "event_type": "consultation",
                    "description": "Reviewed elevated fasting glucose.",
                    "event_date": "2026-01-12",
                    "source_reference": {"document_id": "consult-jan", "page_number": 1, "excerpt": "Reviewed elevated fasting glucose."},
                }
            ],
        },
    ]

    res = builder.build_from_records(records)
    assert isinstance(res, LongitudinalTimelineResult)
    assert res.insufficient_data is False
    assert res.is_clinically_verified is False
    assert "does not establish causation" in res.disclaimer

    # Episode 1 should group lab-before (2026-01-10) and consult-jan (2026-01-12)
    assert len(res.episodes) == 3
    assert res.episodes[0].start_date == "2026-01-10"
    assert res.episodes[0].end_date == "2026-01-12"
    assert set(res.episodes[0].document_ids) == {"consult-jan", "lab-before"}
    assert "Fasting Glucose" in res.episodes[0].linked_biomarker_trends
    assert len(res.episodes[0].linked_pattern_ids) >= 1
    assert res.episodes[1].start_date == "2026-02-01"
    assert res.episodes[2].start_date == "2026-03-10"

    # Before-and-after comparison should span 2026-01-10 -> 2026-03-10 with mid consultation anchor
    assert len(res.before_after_comparisons) == 1
    cmp = res.before_after_comparisons[0]
    assert cmp.subject_name == "Fasting Glucose"
    assert cmp.before_value == "145"
    assert cmp.after_value == "102"
    assert cmp.unit == "mg/dL"
    assert "consultation" in (cmp.anchor_event or "")
    assert "2026-01-12" in (cmp.anchor_event or "")
    assert "does not establish causation" in cmp.causal_disclaimer


def test_timeline_medication_changes_over_time():
    """Test medication regimen changes generate before-and-after comparison."""
    builder = LongitudinalTimelineBuilder()
    records = [
        {
            "document_id": "rx-1",
            "verification_status": "verified",
            "document_type": "prescription",
            "document_date": "2026-01-05",
            "medications": [
                {
                    "brand_name": "GlucoSyn",
                    "generic_ingredients": ["Metformin"],
                    "strength": "500 mg",
                    "dosage": "1 tablet",
                    "frequency": "Once daily",
                    "source_reference": {"document_id": "rx-1", "page_number": 1, "excerpt": "Metformin 500 mg OD"},
                }
            ],
        },
        {
            "document_id": "rx-2",
            "verification_status": "verified",
            "document_type": "prescription",
            "document_date": "2026-02-20",
            "medications": [
                {
                    "brand_name": "GlucoSyn",
                    "generic_ingredients": ["Metformin"],
                    "strength": "500 mg",
                    "dosage": "1 tablet",
                    "frequency": "Twice daily",
                    "source_reference": {"document_id": "rx-2", "page_number": 1, "excerpt": "Metformin 500 mg BID"},
                }
            ],
        },
    ]

    res = builder.build_from_records(records)
    assert len(res.before_after_comparisons) == 1
    med_cmp = res.before_after_comparisons[0]
    assert med_cmp.subject_type == "medication"
    assert med_cmp.subject_name == "metformin"
    assert "Once daily" in med_cmp.before_value
    assert "Twice daily" in med_cmp.after_value


def test_timeline_corroborates_same_event_and_flags_duplicate_documents():
    """Test multiple documents describing the same clinical event and duplicate document_id."""
    builder = LongitudinalTimelineBuilder()
    records = [
        {
            "document_id": "doc-a",
            "verification_status": "verified",
            "document_type": "discharge_summary",
            "document_date": "2026-01-14",
            "clinical_events": [
                {
                    "event_type": "discharge",
                    "description": "Discharged in stable condition.",
                    "event_date": "2026-01-14",
                    "source_reference": {"document_id": "doc-a", "page_number": 1, "excerpt": "Discharged in stable condition."},
                }
            ],
        },
        {
            "document_id": "doc-b",
            "verification_status": "verified",
            "document_type": "clinical_note",
            "document_date": "2026-01-14",
            "clinical_events": [
                {
                    "event_type": "discharge",
                    "description": "Discharged in stable condition.",
                    "event_date": "2026-01-14",
                    "source_reference": {"document_id": "doc-b", "page_number": 2, "excerpt": "Patient discharged in stable condition."},
                }
            ],
        },
        # Duplicate document_id
        {
            "document_id": "doc-a",
            "verification_status": "verified",
            "document_type": "discharge_summary",
            "document_date": "2026-01-14",
            "clinical_events": [],
        },
    ]

    res = builder.build_from_records(records)
    ep = res.episodes[0]
    # Identical discharge event deduplicated to 1 verified_event, while both SourceReferences are preserved
    discharge_events = [e for e in ep.verified_events if e.event_type == "discharge"]
    assert len(discharge_events) == 1
    assert len(ep.duplicate_or_repeated_notes) >= 1
    assert len(ep.source_references) == 2
    assert any("Duplicate document_id" in u.reason for u in res.uncertainty_flags)


def test_timeline_conflicting_events_and_missing_provenance():
    """Test conflicting events on same date and missing source_reference reporting."""
    builder = LongitudinalTimelineBuilder()
    records = [
        {
            "document_id": "doc-1",
            "verification_status": "verified",
            "document_type": "clinical_note",
            "document_date": "2026-04-01",
            "clinical_events": [
                {
                    "event_type": "diagnosis",
                    "description": "Acute viral pharyngitis.",
                    "event_date": "2026-04-01",
                    "source_reference": None,
                }
            ],
        },
        {
            "document_id": "doc-2",
            "verification_status": "verified",
            "document_type": "discharge_summary",
            "document_date": "2026-04-01",
            "clinical_events": [
                {
                    "event_type": "diagnosis",
                    "description": "Bacterial tonsillitis.",
                    "event_date": "2026-04-01",
                    "source_reference": {"document_id": "doc-2", "page_number": 1, "excerpt": "Dx: Bacterial tonsillitis."},
                }
            ],
        },
    ]

    res = builder.build_from_records(records)
    assert any(c.conflict_type == "clinical_event_conflict" for c in res.conflicts)
    assert any("Missing source_reference" in m for m in res.missing_information)


def test_timeline_missing_invalid_dates_and_incompatible_units():
    """Test missing/invalid dates are never invented and incompatible units are excluded from comparisons."""
    builder = LongitudinalTimelineBuilder()
    records = [
        {
            "document_id": "d-invalid-date",
            "verification_status": "verified",
            "document_type": "clinical_note",
            "document_date": "sometime-last-year",
            "clinical_events": [
                {"event_type": "symptom", "description": "Reported mild fatigue.", "event_date": "sometime-last-year"}
            ],
        },
        {
            "document_id": "d-missing-date",
            "verification_status": "verified",
            "document_type": "clinical_note",
            "document_date": None,
            "clinical_events": [
                {"event_type": "symptom", "description": "Reported knee stiffness.", "event_date": None}
            ],
        },
        {
            "document_id": "d-glu-1",
            "verification_status": "verified",
            "document_type": "lab_report",
            "document_date": "2026-01-01",
            "biomarkers": [{"name": "Glucose", "value": "110", "numeric_value": 110.0, "unit": "mg/dL"}],
        },
        {
            "document_id": "d-glu-2",
            "verification_status": "verified",
            "document_type": "lab_report",
            "document_date": "2026-02-01",
            "biomarkers": [{"name": "Glucose", "value": "6.1", "numeric_value": 6.1, "unit": "mmol/L"}],
        },
    ]

    res = builder.build_from_records(records)
    # Undated/invalid-date episode placed last without inventing dates
    assert res.episodes[-1].episode_id == "episode_undated"
    assert res.episodes[-1].date_missing is True
    assert res.episodes[-1].date_uncertain is True
    assert res.episodes[-1].start_date is None

    # Incompatible units excluded from before-and-after comparisons and flagged
    assert res.before_after_comparisons == []
    assert any(c.conflict_type == "biomarker_unit_mismatch" for c in res.conflicts)
    assert any("Invalid or unparseable date" in u.reason for u in res.uncertainty_flags)
    assert any("Missing date" in m for m in res.missing_information)


def test_timeline_rejects_unverified_records_and_handles_empty_input():
    """Test unverified records are rejected and empty input returns insufficient_data."""
    builder = LongitudinalTimelineBuilder()

    empty = builder.build_from_records([])
    assert empty.insufficient_data is True
    assert empty.episodes == []

    with pytest.raises(UnverifiedRecordError):
        builder.build_from_records(
            [
                {
                    "document_id": "unverified-1",
                    "verification_status": VerificationStatus.PENDING_REVIEW.value,
                    "document_type": "lab_report",
                    "document_date": "2026-01-01",
                }
            ]
        )
