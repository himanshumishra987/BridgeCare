"""Medication safety-check and reminder tests."""

from __future__ import annotations

from app.models.enums import InteractionSeverity, ReviewStatus
from app.models.medication import InteractionRule


def _add_medication(client, patient, **overrides):
    payload = {
        "brand_name": "Glucophage",
        "generic_name": "metformin",
        "active_ingredients": [{"name": "metformin", "strength": "500", "unit": "mg"}],
        "started_on": "2025-01-01",
        "dose_text": "500 mg twice daily as prescribed",
    }
    payload.update(overrides)
    response = client.post(
        f"/api/v1/patients/{patient['profile_id']}/medications",
        headers=patient["headers"],
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_medication_needs_an_identity(client, patient):
    response = client.post(
        f"/api/v1/patients/{patient['profile_id']}/medications",
        headers=patient["headers"],
        json={"started_on": "2025-01-01"},
    )
    assert response.status_code == 422


def test_medication_cannot_end_before_it_starts(client, patient):
    response = client.post(
        f"/api/v1/patients/{patient['profile_id']}/medications",
        headers=patient["headers"],
        json={
            "generic_name": "metformin",
            "started_on": "2025-05-01",
            "ended_on": "2025-01-01",
        },
    )
    assert response.status_code == 422


def test_dose_text_is_stored_as_recorded(client, patient):
    medication = _add_medication(client, patient)
    assert medication["dose_text"] == "500 mg twice daily as prescribed"
    assert medication["brand_name"] == "Glucophage"
    assert medication["generic_name"] == "metformin"
    assert medication["status"] == "active"


def test_duplicate_active_ingredient_detection(client, patient):
    _add_medication(client, patient)
    _add_medication(
        client,
        patient,
        brand_name="Glycomet",
        generic_name="metformin hydrochloride",
        active_ingredients=[{"name": "Metformin", "strength": "1000", "unit": "mg"}],
    )

    response = client.get(
        f"/api/v1/patients/{patient['profile_id']}/medications/checks/duplicate-ingredients",
        headers=patient["headers"],
    )
    assert response.status_code == 200
    groups = response.json()
    assert len(groups) >= 1
    assert "metformin" in {group["ingredient_key"] for group in groups}
    metformin_group = next(g for g in groups if "metformin" == g["ingredient_key"])
    assert len(metformin_group["medications"]) == 2


def test_stopped_medication_is_excluded_from_duplicate_check(client, patient):
    first = _add_medication(client, patient)
    _add_medication(
        client,
        patient,
        brand_name="Glycomet",
        active_ingredients=[{"name": "metformin", "strength": "1000", "unit": "mg"}],
    )
    client.post(
        f"/api/v1/medications/{first['id']}/stop",
        headers=patient["headers"],
        json={"ended_on": "2025-02-01"},
    )
    groups = client.get(
        f"/api/v1/patients/{patient['profile_id']}/medications/checks/duplicate-ingredients",
        headers=patient["headers"],
    ).json()
    assert groups == []


def test_overlapping_prescription_periods_detected(client, patient):
    _add_medication(client, patient, started_on="2025-01-01", ended_on="2025-03-01")
    _add_medication(
        client,
        patient,
        brand_name="Glycomet",
        generic_name="metformin",
        started_on="2025-02-01",
        ended_on="2025-04-01",
    )
    overlaps = client.get(
        f"/api/v1/patients/{patient['profile_id']}/medications/checks/overlaps",
        headers=patient["headers"],
    ).json()
    assert len(overlaps) == 1
    assert overlaps[0]["overlap_start"] == "2025-02-01"
    assert overlaps[0]["overlap_end"] == "2025-03-01"


def test_non_overlapping_periods_are_not_reported(client, patient):
    _add_medication(client, patient, started_on="2025-01-01", ended_on="2025-02-01")
    _add_medication(
        client,
        patient,
        brand_name="Glycomet",
        started_on="2025-03-01",
        ended_on="2025-04-01",
    )
    overlaps = client.get(
        f"/api/v1/patients/{patient['profile_id']}/medications/checks/overlaps",
        headers=patient["headers"],
    ).json()
    assert overlaps == []


def test_interaction_warnings_come_only_from_curated_rules(client, db_session, patient):
    _add_medication(
        client,
        patient,
        brand_name="Coumadin",
        generic_name="warfarin",
        active_ingredients=[{"name": "warfarin", "strength": "5", "unit": "mg"}],
    )
    _add_medication(
        client,
        patient,
        brand_name="Disprin",
        generic_name="aspirin",
        active_ingredients=[{"name": "aspirin", "strength": "75", "unit": "mg"}],
    )

    empty = client.get(
        f"/api/v1/patients/{patient['profile_id']}/medications/checks/interaction-warnings",
        headers=patient["headers"],
    ).json()
    assert empty["warnings"] == []
    assert "does not recommend" in empty["disclaimer"]

    db_session.add(
        InteractionRule(
            ingredient_a="aspirin",
            ingredient_b="warfarin",
            severity=InteractionSeverity.MAJOR,
            summary="Increased bleeding risk when used together.",
            source_reference="Test reference: curated interaction monograph",
            review_status=ReviewStatus.REVIEWED,
            reviewed_by="Dr. Test Reviewer",
        )
    )
    db_session.flush()

    response = client.get(
        f"/api/v1/patients/{patient['profile_id']}/medications/checks/interaction-warnings",
        headers=patient["headers"],
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["warnings"]) == 1
    warning = body["warnings"][0]
    assert warning["severity"] == "major"
    assert warning["source_reference"].startswith("Test reference")
    assert warning["professional_review_status"] == "reviewed"
    assert warning["reviewed_by"] == "Dr. Test Reviewer"
    assert warning["advice"] is None
    assert body["rules_reviewed"] == 1


def test_schedule_and_reminder_roundtrip(client, patient):
    medication = _add_medication(client, patient)
    schedule = client.post(
        f"/api/v1/medications/{medication['id']}/schedules",
        headers=patient["headers"],
        json={
            "frequency": "twice_daily",
            "times": ["08:00", "20:00"],
            "timezone": "Asia/Kolkata",
            "instructions_text": "As prescribed",
        },
    )
    assert schedule.status_code == 201, schedule.text
    schedule_body = schedule.json()
    assert schedule_body["times"] == ["08:00", "20:00"]

    reminder = client.post(
        f"/api/v1/patients/{patient['profile_id']}/reminders",
        headers=patient["headers"],
        json={
            "kind": "medication",
            "title": "Take metformin",
            "due_at": "2025-06-01T08:00:00Z",
            "recurrence": "daily",
            "medication_schedule_id": schedule_body["id"],
        },
    )
    assert reminder.status_code == 201, reminder.text
    reminder_id = reminder.json()["id"]

    completed = client.patch(
        f"/api/v1/reminders/{reminder_id}",
        headers=patient["headers"],
        json={"completed": True},
    )
    assert completed.status_code == 200
    assert completed.json()["completed_at"] is not None

    listed = client.get(
        f"/api/v1/patients/{patient['profile_id']}/reminders",
        headers=patient["headers"],
    )
    assert listed.status_code == 200
    assert listed.json()["meta"]["total"] == 1


def test_invalid_schedule_time_is_rejected(client, patient):
    medication = _add_medication(client, patient)
    response = client.post(
        f"/api/v1/medications/{medication['id']}/schedules",
        headers=patient["headers"],
        json={"frequency": "once_daily", "times": ["8am"]},
    )
    assert response.status_code == 422


def test_reminder_cannot_link_another_patients_schedule(client, patient, other_patient):
    medication = _add_medication(client, other_patient)
    schedule = client.post(
        f"/api/v1/medications/{medication['id']}/schedules",
        headers=other_patient["headers"],
        json={"frequency": "once_daily", "times": ["09:00"]},
    ).json()
    response = client.post(
        f"/api/v1/patients/{patient['profile_id']}/reminders",
        headers=patient["headers"],
        json={
            "kind": "medication",
            "title": "Cross-patient reminder",
            "due_at": "2025-06-01T08:00:00Z",
            "medication_schedule_id": schedule["id"],
        },
    )
    assert response.status_code == 422


def test_stopping_medication_records_end_date(client, patient):
    medication = _add_medication(client, patient)
    stopped = client.post(
        f"/api/v1/medications/{medication['id']}/stop",
        headers=patient["headers"],
        json={"ended_on": "2025-02-15", "reason": "Completed course"},
    )
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopped"
    assert stopped.json()["ended_on"] == "2025-02-15"
