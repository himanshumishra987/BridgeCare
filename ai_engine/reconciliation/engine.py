"""Cross-Document Medical Intelligence and Reconciliation engine."""

from typing import Any, Optional

from pydantic import ValidationError

from ai_engine.providers.exceptions import UnverifiedRecordError
from ai_engine.reconciliation.biomarkers import reconcile_biomarkers
from ai_engine.reconciliation.medications import reconcile_medications
from ai_engine.reconciliation.timeline import build_chronological_timeline
from ai_engine.schemas.common import FieldUncertainty
from ai_engine.schemas.reconciliation import (
    ConflictSeverity,
    CrossDocumentConflict,
    ReconciliationResult,
)
from ai_engine.schemas.summary import VerifiedRecordInput


class CrossDocumentReconciler:
    """Reconciles multiple human-verified medical records into longitudinal intelligence.

    Enforces strict human-verification gating (only 'verified' and 'edited_verified'
    records are accepted). Performs biomarker trend analysis, medication reconciliation,
    conflict detection, and chronological timeline construction without hallucination.
    """

    def reconcile(self, verified_records: list[dict[str, Any]]) -> ReconciliationResult:
        """Validate verification statuses and reconcile records deterministically."""
        if not isinstance(verified_records, list):
            raise UnverifiedRecordError(
                "verified_records must be a list of human-verified record dictionaries.",
                provider="reconciliation",
            )

        if not verified_records:
            return ReconciliationResult(
                insufficient_data=True,
                uncertainty_flags=[
                    FieldUncertainty(
                        field_name="verified_records",
                        reason="No human-verified records provided for reconciliation.",
                    )
                ],
                is_clinically_verified=False,
            )

        validated_records: list[VerifiedRecordInput] = []
        for idx, rec in enumerate(verified_records):
            if not isinstance(rec, dict):
                raise UnverifiedRecordError(
                    f"Record at index {idx} must be a dictionary with an approved verification_status.",
                    provider="reconciliation",
                )
            try:
                validated_records.append(VerifiedRecordInput.model_validate(rec))
            except ValidationError as e:
                raise UnverifiedRecordError(
                    f"Record at index {idx} rejected: only 'verified' and 'edited_verified' "
                    "records are permitted for reconciliation.",
                    provider="reconciliation",
                ) from e

        biomarker_trends, bio_conflicts, bio_uncertainties = reconcile_biomarkers(validated_records)
        reconciled_meds, med_conflicts = reconcile_medications(validated_records)
        timeline = build_chronological_timeline(validated_records)
        metadata_conflicts = self._detect_metadata_conflicts(validated_records)

        all_conflicts = bio_conflicts + med_conflicts + metadata_conflicts
        source_record_ids = sorted({r.document_id for r in validated_records if r.document_id})

        has_any_data = bool(biomarker_trends or reconciled_meds or timeline)

        return ReconciliationResult(
            insufficient_data=not has_any_data,
            source_record_ids=source_record_ids,
            biomarker_trends=biomarker_trends,
            reconciled_medications=reconciled_meds,
            conflicts=all_conflicts,
            timeline=timeline,
            uncertainty_flags=bio_uncertainties,
            is_clinically_verified=False,
        )

    @staticmethod
    def _detect_metadata_conflicts(
        records: list[VerifiedRecordInput],
    ) -> list[CrossDocumentConflict]:
        """Detect conflicting patient_name metadata across verified records."""
        names_to_docs: dict[str, list[str]] = {}
        display_names: dict[str, str] = {}

        for rec in records:
            if rec.patient_name and rec.patient_name.strip():
                norm = " ".join(rec.patient_name.strip().split()).lower()
                display_names.setdefault(norm, rec.patient_name.strip())
                if rec.document_id:
                    names_to_docs.setdefault(norm, []).append(rec.document_id)

        if len(display_names) > 1:
            doc_ids = sorted({d for docs in names_to_docs.values() for d in docs})
            return [
                CrossDocumentConflict(
                    conflict_type="patient_metadata_mismatch",
                    field_name="patient_name",
                    severity=ConflictSeverity.MEDIUM,
                    description=(
                        f"Multiple distinct patient names found across verified records: "
                        f"{sorted(display_names.values())}."
                    ),
                    document_ids=doc_ids,
                )
            ]
        return []
