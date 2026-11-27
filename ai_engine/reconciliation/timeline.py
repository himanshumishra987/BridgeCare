"""Chronological clinical timeline builder for verified medical records."""

from ai_engine.reconciliation.biomarkers import (
    _parse_date_sort_key,
    _safe_source_ref,
    parse_valid_date,
)
from ai_engine.schemas.reconciliation import TimelineEvent
from ai_engine.schemas.summary import VerifiedRecordInput


def build_chronological_timeline(
    records: list[VerifiedRecordInput],
) -> list[TimelineEvent]:
    """Construct a chronologically sorted timeline from verified clinical events and documents."""
    events: list[TimelineEvent] = []

    for rec in records:
        if rec.clinical_events:
            for ev in rec.clinical_events:
                if not isinstance(ev, dict):
                    continue
                ev_type = str(ev.get("event_type") or "").strip()
                desc = str(ev.get("description") or "").strip()
                if not ev_type or not desc:
                    continue
                ev_date = ev.get("event_date") or rec.document_date
                is_valid_date = parse_valid_date(ev_date) is not None
                events.append(
                    TimelineEvent(
                        event_date=ev_date,
                        date_missing=not is_valid_date,
                        event_type=ev_type,
                        description=desc,
                        document_id=rec.document_id,
                        document_type=rec.document_type,
                        source_reference=_safe_source_ref(ev.get("source_reference"), rec.document_id),
                    )
                )
        else:
            summary_parts = []
            if rec.document_type:
                summary_parts.append(rec.document_type.replace("_", " ").title())
            if rec.hospital_or_lab_name:
                summary_parts.append(f"at {rec.hospital_or_lab_name}")
            if rec.biomarkers:
                summary_parts.append(f"({len(rec.biomarkers)} biomarker(s))")
            if rec.medications:
                summary_parts.append(f"({len(rec.medications)} medication(s))")

            desc = " ".join(summary_parts) if summary_parts else "Verified medical record"
            is_valid_date = parse_valid_date(rec.document_date) is not None
            events.append(
                TimelineEvent(
                    event_date=rec.document_date,
                    date_missing=not is_valid_date,
                    event_type="document_record",
                    description=desc,
                    document_id=rec.document_id,
                    document_type=rec.document_type,
                    source_reference=None,
                )
            )

    return sorted(events, key=lambda e: _parse_date_sort_key(e.event_date))
