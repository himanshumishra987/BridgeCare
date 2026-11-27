"""Cross-document medication reconciliation and duplicate/conflict detection."""

from collections import defaultdict
from typing import Any, Optional

from ai_engine.reconciliation.biomarkers import (
    _parse_date_sort_key,
    _safe_source_ref,
    parse_valid_date,
)
from ai_engine.schemas.common import SourceReference
from ai_engine.schemas.reconciliation import (
    ConflictSeverity,
    CrossDocumentConflict,
    MedicationReconciliationStatus,
    ReconciledMedication,
)
from ai_engine.schemas.summary import VerifiedRecordInput


def _norm_str(val: Optional[str]) -> str:
    return " ".join((val or "").strip().split()).lower()


def _regimens_differ(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Return True only when both entries specify non-empty values for a field and they differ."""
    for field in ("strength", "dosage", "frequency"):
        va = _norm_str(a.get(field))
        vb = _norm_str(b.get(field))
        if va and vb and va != vb:
            return True
    return False


def reconcile_medications(
    records: list[VerifiedRecordInput],
) -> tuple[list[ReconciledMedication], list[CrossDocumentConflict]]:
    """Reconcile medications across verified records, detecting dose changes, duplicates, and conflicts."""
    # First pass: map known brand names to their canonical generic key
    brand_to_generic_key: dict[str, str] = {}
    raw_items: list[tuple[Optional[str], list[str], dict[str, Any], VerifiedRecordInput]] = []

    for rec in records:
        for med in rec.medications:
            if not isinstance(med, dict):
                continue
            brand = (med.get("brand_name") or "").strip() or None
            generics = [
                " ".join(str(g).strip().split())
                for g in (med.get("generic_ingredients") or [])
                if g and str(g).strip()
            ]
            if not brand and not generics:
                continue
            if brand and generics:
                generic_key = " + ".join(sorted({g.lower() for g in generics}))
                brand_to_generic_key.setdefault(brand.lower(), generic_key)
            raw_items.append((brand, generics, med, rec))

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for brand, generics, med, rec in raw_items:
        if generics:
            key = " + ".join(sorted({g.lower() for g in generics}))
        elif brand and brand.lower() in brand_to_generic_key:
            key = brand_to_generic_key[brand.lower()]
        else:
            key = brand.lower()  # type: ignore[union-attr]

        grouped[key].append(
            {
                "document_id": rec.document_id,
                "document_date": rec.document_date,
                "brand_name": brand,
                "generic_ingredients": generics,
                "strength": med.get("strength"),
                "dosage": med.get("dosage"),
                "frequency": med.get("frequency"),
                "duration": med.get("duration"),
                "instructions": med.get("instructions"),
                "source_reference": _safe_source_ref(med.get("source_reference"), rec.document_id),
            }
        )

    reconciled: list[ReconciledMedication] = []
    conflicts: list[CrossDocumentConflict] = []

    for key in sorted(grouped.keys()):
        entries = sorted(grouped[key], key=lambda e: _parse_date_sort_key(e.get("document_date")))
        brands = sorted({e["brand_name"] for e in entries if e.get("brand_name")})
        generics = sorted({g for e in entries for g in e.get("generic_ingredients", [])})
        refs: list[SourceReference] = [
            e["source_reference"] for e in entries if e.get("source_reference") is not None
        ]
        doc_ids = sorted({e["document_id"] for e in entries if e.get("document_id")})

        notes: list[str] = []
        status = MedicationReconciliationStatus.SINGLE_RECORD

        if len(entries) > 1:
            has_duplicate_brands = len({b.lower() for b in brands}) > 1 and bool(generics)
            has_missing_fields = any(
                not _norm_str(e.get("dosage")) or not _norm_str(e.get("frequency"))
                for e in entries
            )
            if has_missing_fields:
                notes.append("Dosage or frequency missing in one or more records; regimen comparison is partial.")

            # Check for same-date conflicting regimens (only when both entries have explicit differing values)
            by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for e in entries:
                dt = parse_valid_date(e.get("document_date"))
                if dt is not None:
                    by_date[dt.strftime("%Y-%m-%d")].append(e)

            same_date_conflict = False
            for date_key, day_entries in by_date.items():
                if len(day_entries) > 1:
                    day_differs = any(
                        _regimens_differ(day_entries[i], day_entries[j])
                        for i in range(len(day_entries))
                        for j in range(i + 1, len(day_entries))
                    )
                    if day_differs:
                        same_date_conflict = True
                        conflicts.append(
                            CrossDocumentConflict(
                                conflict_type="medication_regimen_conflict",
                                field_name=key,
                                severity=ConflictSeverity.HIGH,
                                description=(
                                    f"Conflicting regimens for '{key}' recorded on {date_key} "
                                    "across verified documents."
                                ),
                                document_ids=sorted({x["document_id"] for x in day_entries if x.get("document_id")}),
                                source_references=[
                                    x["source_reference"] for x in day_entries if x.get("source_reference") is not None
                                ],
                            )
                        )

            any_regimen_changed = any(
                _regimens_differ(entries[i], entries[j])
                for i in range(len(entries))
                for j in range(i + 1, len(entries))
            )

            if same_date_conflict:
                status = MedicationReconciliationStatus.CONFLICTING
                notes.append("Conflicting dosage/frequency regimens found on the same date.")
            elif has_duplicate_brands:
                status = MedicationReconciliationStatus.DUPLICATE_INGREDIENT
                notes.append(
                    f"Multiple brand names ({', '.join(brands)}) share active ingredient '{', '.join(generics)}'."
                )
                conflicts.append(
                    CrossDocumentConflict(
                        conflict_type="duplicate_active_ingredient",
                        field_name=key,
                        severity=ConflictSeverity.HIGH,
                        description=(
                            f"Potential duplicate active ingredient '{', '.join(generics)}' across "
                            f"brands: {', '.join(brands)}."
                        ),
                        document_ids=doc_ids,
                        source_references=refs,
                    )
                )
            elif any_regimen_changed:
                status = MedicationReconciliationStatus.DOSE_OR_FREQUENCY_CHANGED
                notes.append("Medication strength, dosage, or frequency changed across verified dates.")
            else:
                status = MedicationReconciliationStatus.CONSISTENT
                if not has_missing_fields:
                    notes.append("Consistent regimen documented across verified records.")

        serialized_regimens = [
            {
                "document_id": e["document_id"],
                "document_date": e["document_date"],
                "brand_name": e["brand_name"],
                "strength": e["strength"],
                "dosage": e["dosage"],
                "frequency": e["frequency"],
                "duration": e["duration"],
                "instructions": e["instructions"],
            }
            for e in entries
        ]

        reconciled.append(
            ReconciledMedication(
                medication_key=key,
                brand_names=brands,
                generic_ingredients=generics,
                status=status,
                regimens=serialized_regimens,
                notes=notes,
                source_references=refs,
            )
        )

    return reconciled, conflicts
