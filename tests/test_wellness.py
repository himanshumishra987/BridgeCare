"""Holistic health (AYUSH) tests."""

from __future__ import annotations

from app.models.enums import InteractionSeverity, ReviewStatus
from app.models.wellness import HerbDrugOverlapRule


def _add(client, patient, **overrides):
    payload = {
        "care_system": "ayurveda",
        "record_type": "herbal_formulation",
        "title": "Ashwagandha churna",
        "recorded_at": "2025-02-01T10:00:00Z",
        "practitioner_name": "Vaidya Sharma",
        "herbs": [
            {
                "name": "Ashwagandha",
                "botanical_name": "Withania somnifera",
                "part": "root",
                "form": "powder",
                "dose_text": "as advised",
            }
        ],
        "formulation_name": "Ashwagandha Churna",
        "documented_ingredients": [{"name": "Withania somnifera"}],
    }
    payload.update(overrides)
    response = client.post(
        f"/api/v1/patients/{patient['profile_id']}/wellness",
        headers=patient["headers"],
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_wellness_record_keeps_care_system_and_herb_details(client, patient):
    record = _add(client, patient)
    assert record["care_system"] == "ayurveda"
    assert record["herbs"][0]["botanical_name"] == "Withania somnifera"
    assert record["formulation_name"] == "Ashwagandha Churna"
    assert record["verification_status"] == "unverified"


def test_care_systems_remain_distinguishable(client, patient):
    _add(client, patient)
    _add(
        client,
        patient,
        care_system="homoeopathy",
        record_type="consultation",
        title="Homoeopathic consult",
        herbs=[],
        formulation_name=None,
        documented_ingredients=[],
    )

    all_records = client.get(
        f"/api/v1/patients/{patient['profile_id']}/wellness", headers=patient["headers"]
    ).json()
    assert all_records["meta"]["total"] == 2

    ayurveda_only = client.get(
        f"/api/v1/patients/{patient['profile_id']}/wellness",
        headers=patient["headers"],
        params={"care_system": "ayurveda"},
    ).json()
    assert ayurveda_only["meta"]["total"] == 1
    assert ayurveda_only["items"][0]["care_system"] == "ayurveda"


def test_herb_entry_requires_a_name(client, patient):
    response = client.post(
        f"/api/v1/patients/{patient['profile_id']}/wellness",
        headers=patient["headers"],
        json={
            "care_system": "ayurveda",
            "record_type": "herbal_formulation",
            "title": "Nameless herb",
            "recorded_at": "2025-02-01T10:00:00Z",
            "herbs": [{"name": ""}],
        },
    )
    assert response.status_code == 422


def test_herb_drug_overlap_requires_a_curated_rule(client, db_session, patient):
    _add(client, patient)
    client.post(
        f"/api/v1/patients/{patient['profile_id']}/medications",
        headers=patient["headers"],
        json={
            "generic_name": "warfarin",
            "active_ingredients": [{"name": "warfarin", "strength": "5", "unit": "mg"}],
            "started_on": "2025-01-01",
        },
    )

    empty = client.get(
        f"/api/v1/patients/{patient['profile_id']}/wellness/checks/herb-drug-overlaps",
        headers=patient["headers"],
    )
    assert empty.status_code == 200
    assert empty.json()["overlaps"] == []

    db_session.add(
        HerbDrugOverlapRule(
            herb_key="ashwagandha",
            drug_ingredient_key="warfarin",
            severity=InteractionSeverity.MODERATE,
            evidence_summary="Case reports describe altered anticoagulant effect.",
            source_reference="Test reference: herb interaction compendium",
            review_status=ReviewStatus.IN_REVIEW,
        )
    )
    db_session.flush()

    response = client.get(
        f"/api/v1/patients/{patient['profile_id']}/wellness/checks/herb-drug-overlaps",
        headers=patient["headers"],
    )
    body = response.json()
    assert len(body["overlaps"]) == 1
    overlap = body["overlaps"][0]
    assert overlap["source_reference"].startswith("Test reference")
    assert overlap["evidence_summary"]
    assert overlap["professional_review_status"] == "in_review"
    assert overlap["requires_professional_review"] is True
    assert overlap["care_system"] == "ayurveda"
    assert "does not recommend" in overlap["disclaimer"]


def test_wellness_source_document_must_belong_to_patient(client, patient):
    response = client.post(
        f"/api/v1/patients/{patient['profile_id']}/wellness",
        headers=patient["headers"],
        json={
            "care_system": "siddha",
            "record_type": "consultation",
            "title": "Siddha consult",
            "recorded_at": "2025-02-01T10:00:00Z",
            "source_document_id": "00000000-0000-4000-8000-000000000000",
        },
    )
    assert response.status_code == 422
