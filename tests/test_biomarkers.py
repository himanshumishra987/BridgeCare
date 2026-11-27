"""Biomarker analytics tests: units, reference ranges and comparability."""

from __future__ import annotations

import pytest


def _add(client, patient, **overrides):
    payload = {
        "analyte_key": "hemoglobin",
        "analyte_display": "Hemoglobin",
        "value_numeric": "13.2",
        "unit": "g/dL",
        "collected_at": "2025-01-01T00:00:00Z",
        "lab_name": "Sunrise Diagnostics",
        "ref_low": "12.0",
        "ref_high": "16.0",
        "ref_text": "12.0 - 16.0 g/dL",
    }
    payload.update(overrides)
    response = client.post(
        f"/api/v1/patients/{patient['profile_id']}/biomarkers",
        headers=patient["headers"],
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_measurement_preserves_original_unit_and_reference_range(client, patient):
    result = _add(
        client,
        patient,
        unit="g/L",
        value_numeric="132",
        original_unit="g/L",
        original_value_text="132 g/L",
    )
    assert result["unit"] == "g/L"
    assert result["original_unit"] == "g/L"
    assert result["original_value_text"] == "132 g/L"
    assert result["ref_low"] == "12.0"
    assert result["ref_high"] == "16.0"
    assert result["lab_name"] == "Sunrise Diagnostics"
    assert result["verification_status"] == "unverified"


def test_measurement_requires_a_value(client, patient):
    response = client.post(
        f"/api/v1/patients/{patient['profile_id']}/biomarkers",
        headers=patient["headers"],
        json={
            "analyte_key": "hemoglobin",
            "analyte_display": "Hemoglobin",
            "unit": "g/dL",
            "collected_at": "2025-01-01T00:00:00Z",
        },
    )
    assert response.status_code == 422


def test_trend_converts_compatible_units_to_one_canonical_unit(client, patient):
    _add(client, patient, value_numeric="13.2", unit="g/dL", collected_at="2025-01-01T00:00:00Z")
    _add(client, patient, value_numeric="140", unit="g/L", collected_at="2025-06-01T00:00:00Z")

    trend = client.get(
        f"/api/v1/patients/{patient['profile_id']}/biomarkers/hemoglobin/trend",
        headers=patient["headers"],
    )
    assert trend.status_code == 200
    body = trend.json()
    assert body["unit"] == "g/dL"
    assert body["comparable"] is True
    values = [point["value"] for point in body["points"]]
    assert values == pytest.approx([13.2, 14.0])
    assert [point["converted"] for point in body["points"]] == [False, True]
    assert body["excluded"] == []


def test_trend_excludes_non_convertible_units_instead_of_mixing_them(client, patient):
    _add(
        client,
        patient,
        analyte_key="hba1c",
        analyte_display="HbA1c",
        value_numeric="6.4",
        unit="%",
        collected_at="2025-01-01T00:00:00Z",
    )
    _add(
        client,
        patient,
        analyte_key="hba1c",
        analyte_display="HbA1c",
        value_numeric="46",
        unit="mmol/mol",
        collected_at="2025-06-01T00:00:00Z",
    )

    trend = client.get(
        f"/api/v1/patients/{patient['profile_id']}/biomarkers/hba1c/trend",
        headers=patient["headers"],
    ).json()
    assert len(trend["points"]) == 1
    assert len(trend["excluded"]) == 1
    assert trend["excluded"][0]["reason"] == "unit_not_comparable"
    assert trend["excluded"][0]["unit"] == "mmol/mol"


def test_different_analytes_are_never_plotted_together(client, patient):
    _add(client, patient, analyte_key="glucose", analyte_display="Glucose", value_numeric="95", unit="mg/dL")
    _add(client, patient, analyte_key="hba1c", analyte_display="HbA1c", value_numeric="6.1", unit="%")

    glucose = client.get(
        f"/api/v1/patients/{patient['profile_id']}/biomarkers/glucose/trend",
        headers=patient["headers"],
    ).json()
    hba1c = client.get(
        f"/api/v1/patients/{patient['profile_id']}/biomarkers/hba1c/trend",
        headers=patient["headers"],
    ).json()
    assert glucose["analyte_key"] == "glucose"
    assert hba1c["analyte_key"] == "hba1c"
    assert glucose["unit"] != hba1c["unit"]


def test_trend_requires_two_points_to_be_comparable(client, patient):
    _add(client, patient)
    trend = client.get(
        f"/api/v1/patients/{patient['profile_id']}/biomarkers/hemoglobin/trend",
        headers=patient["headers"],
    ).json()
    assert trend["comparable"] is False
    assert len(trend["points"]) == 1


def test_listing_analytes_and_summary(client, patient):
    _add(client, patient)
    _add(client, patient, analyte_key="creatinine", analyte_display="Creatinine", value_numeric="0.9", unit="mg/dL")

    analytes = client.get(
        f"/api/v1/patients/{patient['profile_id']}/biomarkers/analytes",
        headers=patient["headers"],
    )
    assert analytes.status_code == 200
    keys = {item["analyte_key"] for item in analytes.json()}
    assert keys == {"hemoglobin", "creatinine"}

    summary = client.get(
        f"/api/v1/patients/{patient['profile_id']}/analytics/summary",
        headers=patient["headers"],
    )
    assert summary.status_code == 200
    body = summary.json()
    assert body["measurement_count"] == 2
    assert body["analyte_count"] == 2


def test_unknown_analyte_trend_returns_not_found(client, patient):
    response = client.get(
        f"/api/v1/patients/{patient['profile_id']}/biomarkers/not_a_real_analyte/trend",
        headers=patient["headers"],
    )
    assert response.status_code == 404
