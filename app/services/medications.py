"""Medication management services.

Safety posture (deliberate and enforced):

* The backend performs **duplicate active-ingredient** detection and
  **overlapping prescription** detection from the data the patient recorded.
* Interaction warnings come only from the curated ``interaction_rules`` table,
  which ships empty and must be populated from a named reference. Every warning
  carries its citation and professional-review status.
* No function in this module returns a recommendation, a dose, or an
  instruction to start/stop/change any medicine.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date
from itertools import combinations
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.enums import InteractionSeverity, MedicationStatus
from app.models.medication import InteractionRule, Medication

NO_MEDICAL_ADVICE_DISCLAIMER = (
    "Informational only. BridgeCare does not recommend starting, stopping or changing "
    "any medicine or dose. Discuss any concern with a qualified clinician or pharmacist."
)

_INGREDIENT_CLEAN_RE = re.compile(r"[^a-z0-9]+")


def normalize_ingredient(name: str) -> str:
    """Normalize a brand/generic/herb name into a comparison key."""
    return _INGREDIENT_CLEAN_RE.sub("_", (name or "").strip().lower()).strip("_")


def medication_display_name(medication: Medication) -> str:
    return (
        medication.brand_name
        or medication.generic_name
        or (medication.active_ingredients[0].get("name") if medication.active_ingredients else None)
        or "Unnamed medication"
    )


def ingredient_keys(medication: Medication) -> set[str]:
    """All comparison keys for a medication (generic name + declared ingredients)."""
    keys: set[str] = set()
    if medication.generic_name:
        keys.add(normalize_ingredient(medication.generic_name))
    for ingredient in medication.active_ingredients or []:
        raw = ingredient.get("name") if isinstance(ingredient, dict) else str(ingredient)
        if raw:
            keys.add(normalize_ingredient(str(raw)))
    keys.discard("")
    return keys


def active_medications(db: Session, *, patient_id: uuid.UUID) -> list[Medication]:
    return list(
        db.scalars(
            select(Medication).where(
                Medication.patient_id == patient_id,
                Medication.status == MedicationStatus.ACTIVE,
            )
        )
    )


@dataclass(frozen=True)
class DuplicateGroup:
    ingredient_key: str
    medications: list[dict[str, Any]]


def duplicate_ingredients(db: Session, *, patient_id: uuid.UUID) -> list[DuplicateGroup]:
    """Active medications sharing at least one active ingredient."""
    by_key: dict[str, list[Medication]] = {}
    for medication in active_medications(db, patient_id=patient_id):
        for key in ingredient_keys(medication):
            by_key.setdefault(key, []).append(medication)

    groups: list[DuplicateGroup] = []
    for key, meds in sorted(by_key.items()):
        if len(meds) < 2:
            continue
        groups.append(
            DuplicateGroup(
                ingredient_key=key,
                medications=[
                    {
                        "id": str(medication.id),
                        "display_name": medication_display_name(medication),
                        "brand_name": medication.brand_name,
                        "generic_name": medication.generic_name,
                        "started_on": medication.started_on,
                        "status": str(medication.status),
                    }
                    for medication in meds
                ],
            )
        )
    return groups


def _effective_range(medication: Medication) -> tuple[date, date]:
    """Inclusive period covered by a medication (open-ended when ongoing)."""
    start = medication.started_on or date.min
    end = medication.ended_on or date.max
    if end < start:
        start, end = end, start
    return start, end


def overlapping_prescriptions(db: Session, *, patient_id: uuid.UUID) -> list[dict[str, Any]]:
    """Pairs of active medications with overlapping recorded dates."""
    meds = active_medications(db, patient_id=patient_id)
    overlaps: list[dict[str, Any]] = []
    for left, right in combinations(meds, 2):
        shared = ingredient_keys(left) & ingredient_keys(right)
        if not shared:
            continue
        left_start, left_end = _effective_range(left)
        right_start, right_end = _effective_range(right)
        overlap_start = max(left_start, right_start)
        overlap_end = min(left_end, right_end)
        if overlap_start > overlap_end:
            continue
        overlaps.append(
            {
                "ingredient_keys": sorted(shared),
                "overlap_start": None if overlap_start == date.min else overlap_start,
                "overlap_end": None if overlap_end == date.max else overlap_end,
                "left": {
                    "id": str(left.id),
                    "display_name": medication_display_name(left),
                    "started_on": left.started_on,
                    "ended_on": left.ended_on,
                },
                "right": {
                    "id": str(right.id),
                    "display_name": medication_display_name(right),
                    "started_on": right.started_on,
                    "ended_on": right.ended_on,
                },
            }
        )
    return overlaps


def interaction_warnings(db: Session, *, patient_id: uuid.UUID) -> dict[str, Any]:
    """Match active medications against curated interaction rules."""
    meds = active_medications(db, patient_id=patient_id)
    if not meds:
        return {"warnings": [], "rules_reviewed": 0, "disclaimer": NO_MEDICAL_ADVICE_DISCLAIMER}

    med_keys = [(medication, ingredient_keys(medication)) for medication in meds]
    all_keys = sorted({key for _, keys in med_keys for key in keys})
    if not all_keys:
        return {"warnings": [], "rules_reviewed": 0, "disclaimer": NO_MEDICAL_ADVICE_DISCLAIMER}

    rules = list(
        db.scalars(
            select(InteractionRule).where(
                or_(
                    InteractionRule.ingredient_a.in_(all_keys),
                    InteractionRule.ingredient_b.in_(all_keys),
                )
            )
        )
    )

    warnings: list[dict[str, Any]] = []
    for rule in rules:
        a, b = rule.ingredient_a, rule.ingredient_b
        med_a = [m for m, keys in med_keys if a in keys and b not in keys]
        med_b = [m for m, keys in med_keys if b in keys and a not in keys]
        for left in med_a:
            for right in med_b:
                if left.id == right.id:
                    continue
                warnings.append(
                    {
                        "severity": str(rule.severity),
                        "summary": rule.summary,
                        "source_reference": rule.source_reference,
                        "source_url": rule.source_url,
                        "professional_review_status": str(rule.review_status),
                        "reviewed_by": rule.reviewed_by,
                        "reviewed_at": rule.reviewed_at,
                        "medications": [
                            {"id": str(left.id), "display_name": medication_display_name(left)},
                            {"id": str(right.id), "display_name": medication_display_name(right)},
                        ],
                        "advice": None,
                        "disclaimer": NO_MEDICAL_ADVICE_DISCLAIMER,
                    }
                )

    severity_order = {
        InteractionSeverity.CONTRAINDICATED: 0,
        InteractionSeverity.MAJOR: 1,
        InteractionSeverity.MODERATE: 2,
        InteractionSeverity.MINOR: 3,
    }
    warnings.sort(key=lambda warning: severity_order.get(InteractionSeverity(warning["severity"]), 9))
    return {
        "warnings": warnings,
        "rules_reviewed": sum(
            1 for rule in rules if str(rule.review_status) == "reviewed"
        ),
        "disclaimer": NO_MEDICAL_ADVICE_DISCLAIMER,
    }


