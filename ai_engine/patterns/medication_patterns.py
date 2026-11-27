"""Medication-history pattern identification warranting human review."""

from ai_engine.schemas.common import ConfidenceCategory, ConfidenceScore
from ai_engine.schemas.patterns import (
    HealthPattern,
    PatternCategory,
    PatternSeverity,
)
from ai_engine.schemas.reconciliation import (
    MedicationReconciliationStatus,
    ReconciledMedication,
)

_SOURCE = "bridgecare:pattern_analyzer"


def identify_medication_patterns(
    reconciled_meds: list[ReconciledMedication],
) -> list[HealthPattern]:
    """Identify medication-history patterns from reconciled medications that warrant human review."""
    patterns: list[HealthPattern] = []

    for med in reconciled_meds:
        if med.status == MedicationReconciliationStatus.CONFLICTING:
            patterns.append(
                HealthPattern(
                    pattern_id=f"med_conflict_{med.medication_key}",
                    category=PatternCategory.MEDICATION_REVIEW,
                    title=f"Conflicting same-date regimens for {med.medication_key}",
                    severity=PatternSeverity.HIGH,
                    explanation=(
                        f"Verified records from the same date document conflicting strength, dosage, "
                        f"or frequency for '{med.medication_key}'. Human/clinician verification required; "
                        "no treatment change is inferred."
                    ),
                    related_medications=[med.medication_key],
                    confidence=ConfidenceScore(
                        score=0.95,
                        source=_SOURCE,
                        category=ConfidenceCategory.HIGH,
                    ),
                    source_references=med.source_references,
                )
            )
        elif med.status == MedicationReconciliationStatus.DUPLICATE_INGREDIENT:
            patterns.append(
                HealthPattern(
                    pattern_id=f"med_duplicate_{med.medication_key}",
                    category=PatternCategory.MEDICATION_REVIEW,
                    title=f"Potential duplicate active ingredient: {med.medication_key}",
                    severity=PatternSeverity.HIGH,
                    explanation=(
                        f"Multiple brand names ({', '.join(med.brand_names)}) share active ingredient "
                        f"'{med.medication_key}'. Flagged for clinician/pharmacist review."
                    ),
                    related_medications=[med.medication_key],
                    confidence=ConfidenceScore(
                        score=0.93,
                        source=_SOURCE,
                        category=ConfidenceCategory.HIGH,
                    ),
                    source_references=med.source_references,
                )
            )
        elif med.status == MedicationReconciliationStatus.DOSE_OR_FREQUENCY_CHANGED and len(med.regimens) >= 3:
            patterns.append(
                HealthPattern(
                    pattern_id=f"med_frequent_changes_{med.medication_key}",
                    category=PatternCategory.MEDICATION_REVIEW,
                    title=f"Multiple regimen changes for {med.medication_key}",
                    severity=PatternSeverity.MEDIUM,
                    explanation=(
                        f"Observed {len(med.regimens)} verified prescriptions with changing strength, "
                        f"dosage, or frequency for '{med.medication_key}'. Flagged for clinician review."
                    ),
                    related_medications=[med.medication_key],
                    confidence=ConfidenceScore(
                        score=0.88,
                        source=_SOURCE,
                        category=ConfidenceCategory.HIGH,
                    ),
                    source_references=med.source_references,
                )
            )

        if any("missing" in n.lower() for n in med.notes):
            patterns.append(
                HealthPattern(
                    pattern_id=f"med_incomplete_regimen_{med.medication_key}",
                    category=PatternCategory.MEDICATION_REVIEW,
                    title=f"Incomplete dosage/frequency documentation for {med.medication_key}",
                    severity=PatternSeverity.LOW,
                    explanation=(
                        f"One or more verified records for '{med.medication_key}' are missing explicit "
                        "dosage or frequency instructions. Do not infer missing instructions."
                    ),
                    related_medications=[med.medication_key],
                    confidence=ConfidenceScore(
                        score=0.9,
                        source=_SOURCE,
                        category=ConfidenceCategory.HIGH,
                    ),
                    source_references=med.source_references,
                )
            )

    return patterns
