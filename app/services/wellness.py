"""Holistic health services.

AYUSH records are stored with an explicit ``care_system`` so they are never
conflated with allopathic records. Herb–drug overlap warnings use the same
evidence-and-review posture as drug interactions: curated rules only, each with
a citation and a professional-review status, and no therapeutic advice.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.enums import CareSystem
from app.models.medication import Medication
from app.models.wellness import HerbDrugOverlapRule, WellnessRecord
from app.services.medications import NO_MEDICAL_ADVICE_DISCLAIMER, active_medications, ingredient_keys, medication_display_name, normalize_ingredient

HERB_NAMES_REQUIRED = (
    "Every herb entry must include at least a 'name'; botanical names are stored separately."
)


def normalize_herb(name: str) -> str:
    return normalize_ingredient(name)


def herb_keys(record: WellnessRecord) -> set[str]:
    keys: set[str] = set()
    for herb in record.herbs or []:
        if isinstance(herb, dict):
            for field in ("name", "botanical_name"):
                value = herb.get(field)
                if value:
                    keys.add(normalize_herb(str(value)))
    if record.formulation_name:
        keys.add(normalize_herb(record.formulation_name))
    for ingredient in record.documented_ingredients or []:
        if isinstance(ingredient, dict):
            value = ingredient.get("name")
            if value:
                keys.add(normalize_herb(str(value)))
    keys.discard("")
    return keys


def validate_herb_payload(herbs: list[dict[str, Any]]) -> None:
    for herb in herbs:
        if not isinstance(herb, dict) or not str(herb.get("name", "")).strip():
            from app.core.errors import ValidationAppError

            raise ValidationAppError(HERB_NAMES_REQUIRED)


def herb_drug_overlaps(db: Session, *, patient_id: uuid.UUID) -> dict[str, Any]:
    """Surface curated herb–drug overlap entries for this patient's current data."""
    wellness = list(
        db.scalars(
            select(WellnessRecord).where(WellnessRecord.patient_id == patient_id)
        )
    )
    meds = active_medications(db, patient_id=patient_id)
    if not wellness or not meds:
        return {
            "overlaps": [],
            "disclaimer": NO_MEDICAL_ADVICE_DISCLAIMER,
            "note": "No overlapping herb and medication records to evaluate.",
        }

    herb_index: dict[str, list[WellnessRecord]] = {}
    for record in wellness:
        for key in herb_keys(record):
            herb_index.setdefault(key, []).append(record)

    med_index: dict[str, list[Medication]] = {}
    for medication in meds:
        for key in ingredient_keys(medication):
            med_index.setdefault(key, []).append(medication)

    if not herb_index or not med_index:
        return {
            "overlaps": [],
            "disclaimer": NO_MEDICAL_ADVICE_DISCLAIMER,
            "note": "No overlapping herb and medication records to evaluate.",
        }

    rules = list(
        db.scalars(
            select(HerbDrugOverlapRule).where(
                or_(
                    HerbDrugOverlapRule.herb_key.in_(list(herb_index)),
                    HerbDrugOverlapRule.drug_ingredient_key.in_(list(med_index)),
                )
            )
        )
    )

    overlaps: list[dict[str, Any]] = []
    for rule in rules:
        herbs = herb_index.get(rule.herb_key, [])
        drugs = med_index.get(rule.drug_ingredient_key, [])
        if not herbs or not drugs:
            continue
        for herb_record in herbs:
            for medication in drugs:
                overlaps.append(
                    {
                        "severity": str(rule.severity),
                        "herb_key": rule.herb_key,
                        "drug_ingredient_key": rule.drug_ingredient_key,
                        "evidence_summary": rule.evidence_summary,
                        "source_reference": rule.source_reference,
                        "source_url": rule.source_url,
                        "professional_review_status": str(rule.review_status),
                        "reviewed_by": rule.reviewed_by,
                        "reviewed_at": rule.reviewed_at,
                        "care_system": str(herb_record.care_system),
                        "wellness_record": {
                            "id": str(herb_record.id),
                            "title": herb_record.title,
                        },
                        "medication": {
                            "id": str(medication.id),
                            "display_name": medication_display_name(medication),
                        },
                        "requires_professional_review": True,
                        "disclaimer": NO_MEDICAL_ADVICE_DISCLAIMER,
                    }
                )

    return {
        "overlaps": overlaps,
        "care_systems_evaluated": sorted({str(record.care_system) for record in wellness}),
        "disclaimer": NO_MEDICAL_ADVICE_DISCLAIMER,
    }


def group_by_care_system(records: list[WellnessRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        key = str(record.care_system)
        counts[key] = counts.get(key, 0) + 1
    return counts


def care_system_values() -> list[str]:
    return [system.value for system in CareSystem]
