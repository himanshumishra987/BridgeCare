"""Before-and-after temporal comparisons for compatible, validly dated records."""

from typing import Optional

from ai_engine.reconciliation.biomarkers import parse_valid_date
from ai_engine.schemas.common import SourceReference
from ai_engine.schemas.longitudinal_timeline import BeforeAfterComparison
from ai_engine.schemas.reconciliation import (
    MedicationReconciliationStatus,
    ReconciliationResult,
    TimelineEvent,
)


def _find_anchor_event(
    timeline: list[TimelineEvent],
    before_iso: str,
    after_iso: str,
) -> Optional[str]:
    """Find a clinical event occurring strictly between before_iso and after_iso."""
    for ev in timeline:
        dt = parse_valid_date(ev.event_date)
        if dt is None:
            continue
        ev_iso = dt.strftime("%Y-%m-%d")
        if before_iso < ev_iso < after_iso and ev.event_type in (
            "discharge",
            "admission",
            "consultation",
            "procedure",
            "diagnosis",
            "document_record",
        ):
            return f"{ev.event_type} on {ev.event_date}: {ev.description}"
    return None


def build_before_after_comparisons(
    reconciliation: ReconciliationResult,
) -> list[BeforeAfterComparison]:
    """Build before-and-after comparisons from comparable dated biomarkers and medications."""
    comparisons: list[BeforeAfterComparison] = []

    # 1. Biomarker before-and-after comparisons (only when is_comparable=True)
    for trend in reconciliation.biomarker_trends:
        if not trend.is_comparable:
            continue

        dated_pts = [
            p for p in trend.data_points
            if parse_valid_date(p.recorded_date) is not None and p.numeric_value is not None
        ]
        if len(dated_pts) < 2:
            continue

        first, last = dated_pts[0], dated_pts[-1]
        dt_first = parse_valid_date(first.recorded_date)
        dt_last = parse_valid_date(last.recorded_date)
        assert dt_first is not None and dt_last is not None
        if dt_first == dt_last:
            continue

        anchor = _find_anchor_event(
            reconciliation.timeline,
            dt_first.strftime("%Y-%m-%d"),
            dt_last.strftime("%Y-%m-%d"),
        )
        refs: list[SourceReference] = [
            r for r in (first.source_reference, last.source_reference) if r is not None
        ]
        unit_str = f" {trend.normalized_unit}" if trend.normalized_unit else ""
        comparisons.append(
            BeforeAfterComparison(
                subject_type="biomarker",
                subject_name=trend.biomarker_name,
                before_date=first.recorded_date or "",
                before_value=first.value,
                after_date=last.recorded_date or "",
                after_value=last.value,
                unit=trend.normalized_unit,
                change_summary=(
                    f"{trend.biomarker_name} observed at {first.value}{unit_str} on "
                    f"{first.recorded_date} and {last.value}{unit_str} on {last.recorded_date} "
                    f"({trend.trend_direction.value})."
                ),
                anchor_event=anchor,
                source_references=refs,
            )
        )

    # 2. Medication regimen before-and-after comparisons
    for med in reconciliation.reconciled_medications:
        if med.status != MedicationReconciliationStatus.DOSE_OR_FREQUENCY_CHANGED:
            continue
        dated_regs = [
            r for r in med.regimens
            if parse_valid_date(r.get("document_date")) is not None
        ]
        if len(dated_regs) < 2:
            continue

        first_r, last_r = dated_regs[0], dated_regs[-1]
        dt_first = parse_valid_date(first_r.get("document_date"))
        dt_last = parse_valid_date(last_r.get("document_date"))
        assert dt_first is not None and dt_last is not None
        if dt_first == dt_last:
            continue

        before_desc = " ".join(
            str(x) for x in (first_r.get("strength"), first_r.get("dosage"), first_r.get("frequency")) if x
        ).strip() or "documented regimen"
        after_desc = " ".join(
            str(x) for x in (last_r.get("strength"), last_r.get("dosage"), last_r.get("frequency")) if x
        ).strip() or "documented regimen"

        anchor = _find_anchor_event(
            reconciliation.timeline,
            dt_first.strftime("%Y-%m-%d"),
            dt_last.strftime("%Y-%m-%d"),
        )
        comparisons.append(
            BeforeAfterComparison(
                subject_type="medication",
                subject_name=med.medication_key,
                before_date=first_r.get("document_date") or "",
                before_value=before_desc,
                after_date=last_r.get("document_date") or "",
                after_value=after_desc,
                unit=None,
                change_summary=(
                    f"Documented regimen for {med.medication_key} changed from "
                    f"'{before_desc}' ({first_r.get('document_date')}) to "
                    f"'{after_desc}' ({last_r.get('document_date')})."
                ),
                anchor_event=anchor,
                source_references=med.source_references,
            )
        )

    return comparisons
