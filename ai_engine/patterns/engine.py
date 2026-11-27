"""Unified Intelligent Health Pattern Identification engine."""

from typing import Any, Optional

from ai_engine.patterns.biomarker_patterns import identify_biomarker_patterns
from ai_engine.patterns.medication_patterns import identify_medication_patterns
from ai_engine.reconciliation.engine import CrossDocumentReconciler
from ai_engine.schemas.common import FieldUncertainty
from ai_engine.schemas.patterns import PatternIdentificationResult
from ai_engine.schemas.reconciliation import ReconciliationResult


class HealthPatternAnalyzer:
    """Identifies observational health patterns on top of reconciled human-verified records.

    Reuses CrossDocumentReconciler outputs without duplicating trend calculations or
    making clinical diagnoses or treatment recommendations.
    """

    def __init__(self, reconciler: Optional[CrossDocumentReconciler] = None):
        self.reconciler = reconciler or CrossDocumentReconciler()

    def analyze_records(
        self,
        verified_records: list[dict[str, Any]],
    ) -> PatternIdentificationResult:
        """Reconcile human-verified records and identify observational health patterns."""
        reconciliation = self.reconciler.reconcile(verified_records)
        return self.analyze_reconciliation(reconciliation)

    def analyze_reconciliation(
        self,
        reconciliation: ReconciliationResult,
    ) -> PatternIdentificationResult:
        """Identify health patterns directly from a ReconciliationResult."""
        if reconciliation.insufficient_data:
            return PatternIdentificationResult(
                insufficient_data=True,
                source_record_ids=reconciliation.source_record_ids,
                patterns=[],
                uncertainty_flags=list(reconciliation.uncertainty_flags)
                or [
                    FieldUncertainty(
                        field_name="verified_records",
                        reason="Insufficient verified medical data to identify health patterns.",
                    )
                ],
                is_clinically_verified=False,
            )

        bio_patterns, bio_uncertainties = identify_biomarker_patterns(
            reconciliation.biomarker_trends
        )
        med_patterns = identify_medication_patterns(
            reconciliation.reconciled_medications
        )

        all_patterns = bio_patterns + med_patterns
        all_uncertainties = list(reconciliation.uncertainty_flags) + bio_uncertainties

        return PatternIdentificationResult(
            insufficient_data=False,
            source_record_ids=reconciliation.source_record_ids,
            patterns=all_patterns,
            uncertainty_flags=all_uncertainties,
            is_clinically_verified=False,
        )
