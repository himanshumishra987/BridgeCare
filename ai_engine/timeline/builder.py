"""Intelligent Longitudinal Health Timeline builder."""

from collections import defaultdict
from typing import Any, Optional

from ai_engine.patterns.engine import HealthPatternAnalyzer
from ai_engine.reconciliation.biomarkers import parse_valid_date
from ai_engine.reconciliation.engine import CrossDocumentReconciler
from ai_engine.schemas.common import FieldUncertainty, SourceReference
from ai_engine.schemas.longitudinal_timeline import (
    LongitudinalEpisode,
    LongitudinalTimelineResult,
)
from ai_engine.schemas.patterns import PatternIdentificationResult
from ai_engine.schemas.reconciliation import (
    ConflictSeverity,
    CrossDocumentConflict,
    ReconciliationResult,
    TimelineEvent,
)
from ai_engine.timeline.comparisons import build_before_after_comparisons


def _norm_text(text: str) -> str:
    return " ".join(text.strip().split()).lower()


class LongitudinalTimelineBuilder:
    """Builds a unified chronological patient-health journey from human-verified records.

    Reuses CrossDocumentReconciler and HealthPatternAnalyzer without duplicating
    trend calculations or accepting unverified records.
    """

    def __init__(
        self,
        reconciler: Optional[CrossDocumentReconciler] = None,
        pattern_analyzer: Optional[HealthPatternAnalyzer] = None,
        episode_window_days: int = 7,
    ):
        self.reconciler = reconciler or CrossDocumentReconciler()
        self.pattern_analyzer = pattern_analyzer or HealthPatternAnalyzer(self.reconciler)
        self.episode_window_days = max(0, episode_window_days)

    def build_from_records(
        self,
        verified_records: list[dict[str, Any]],
    ) -> LongitudinalTimelineResult:
        """Validate, reconcile, analyze patterns, and build the longitudinal timeline."""
        reconciliation = self.reconciler.reconcile(verified_records)
        pattern_result = self.pattern_analyzer.analyze_reconciliation(reconciliation)
        return self.build_from_reconciliation(
            reconciliation=reconciliation,
            pattern_result=pattern_result,
            raw_records=verified_records,
        )

    def build_from_reconciliation(
        self,
        reconciliation: ReconciliationResult,
        pattern_result: Optional[PatternIdentificationResult] = None,
        raw_records: Optional[list[dict[str, Any]]] = None,
    ) -> LongitudinalTimelineResult:
        """Build longitudinal timeline from pre-computed ReconciliationResult and patterns."""
        patterns_res = pattern_result or self.pattern_analyzer.analyze_reconciliation(reconciliation)

        if reconciliation.insufficient_data:
            return LongitudinalTimelineResult(
                insufficient_data=True,
                source_record_ids=reconciliation.source_record_ids,
                missing_information=["No human-verified clinical events or records available."],
                uncertainty_flags=list(reconciliation.uncertainty_flags),
                is_clinically_verified=False,
            )

        extra_conflicts: list[CrossDocumentConflict] = []
        extra_uncertainties: list[FieldUncertainty] = []
        missing_info: list[str] = []

        # 1. Detect duplicate document IDs if raw_records provided
        if raw_records:
            id_counts: dict[str, int] = defaultdict(int)
            for rec in raw_records:
                doc_id = rec.get("document_id") if isinstance(rec, dict) else None
                if doc_id:
                    id_counts[str(doc_id)] += 1
            dup_ids = sorted(d for d, count in id_counts.items() if count > 1)
            if dup_ids:
                extra_uncertainties.append(
                    FieldUncertainty(
                        field_name="document_id",
                        reason=f"Duplicate document_id(s) detected in input: {dup_ids}.",
                    )
                )

        # 2. Separate validly dated events from missing/invalid-dated events
        dated_events: list[TimelineEvent] = []
        undated_events: list[TimelineEvent] = []

        for ev in reconciliation.timeline:
            dt = parse_valid_date(ev.event_date)
            if dt is None or ev.date_missing:
                undated_events.append(ev)
                if ev.event_date and ev.event_date.strip():
                    extra_uncertainties.append(
                        FieldUncertainty(
                            field_name="event_date",
                            reason=(
                                f"Invalid or unparseable date '{ev.event_date}' for event "
                                f"'{ev.event_type}'; placed in uncertain-date section without inventing a date."
                            ),
                            source_reference=ev.source_reference,
                        )
                    )
                else:
                    missing_info.append(
                        f"Missing date for {ev.event_type} (document: {ev.document_id or 'unknown'})."
                    )
            else:
                dated_events.append(ev)

            if ev.source_reference is None and ev.event_type != "document_record":
                missing_info.append(
                    f"Missing source_reference for {ev.event_type} on {ev.event_date or 'undated record'}."
                )

        # 3. Cluster dated events into chronological episodes
        episodes: list[LongitudinalEpisode] = []
        if dated_events:
            clusters: list[list[TimelineEvent]] = [[dated_events[0]]]
            for ev in dated_events[1:]:
                prev_dt = parse_valid_date(clusters[-1][-1].event_date)
                curr_dt = parse_valid_date(ev.event_date)
                assert prev_dt is not None and curr_dt is not None
                if (curr_dt - prev_dt).days <= self.episode_window_days:
                    clusters[-1].append(ev)
                else:
                    clusters.append([ev])

            for idx, cluster in enumerate(clusters, start=1):
                ep, ep_conflicts = self._build_episode(
                    episode_id=f"episode_{idx}",
                    events=cluster,
                    reconciliation=reconciliation,
                    patterns_res=patterns_res,
                    date_missing=False,
                    date_uncertain=False,
                )
                episodes.append(ep)
                extra_conflicts.extend(ep_conflicts)

        # 4. Append undated/uncertain-date events at the end without fabricating dates
        if undated_events:
            ep, ep_conflicts = self._build_episode(
                episode_id="episode_undated",
                events=undated_events,
                reconciliation=reconciliation,
                patterns_res=patterns_res,
                date_missing=True,
                date_uncertain=True,
            )
            episodes.append(ep)
            extra_conflicts.extend(ep_conflicts)

        # 5. Build before-and-after comparisons from compatible dated records
        comparisons = build_before_after_comparisons(reconciliation)

        all_conflicts = list(reconciliation.conflicts) + extra_conflicts
        all_uncertainties = list(patterns_res.uncertainty_flags) + extra_uncertainties

        return LongitudinalTimelineResult(
            insufficient_data=False,
            source_record_ids=reconciliation.source_record_ids,
            episodes=episodes,
            before_after_comparisons=comparisons,
            conflicts=all_conflicts,
            missing_information=sorted(set(missing_info)),
            uncertainty_flags=all_uncertainties,
            is_clinically_verified=False,
        )

    def _build_episode(
        self,
        episode_id: str,
        events: list[TimelineEvent],
        reconciliation: ReconciliationResult,
        patterns_res: PatternIdentificationResult,
        date_missing: bool,
        date_uncertain: bool,
    ) -> tuple[LongitudinalEpisode, list[CrossDocumentConflict]]:
        """Assemble a LongitudinalEpisode, deduplicating repeated events and detecting conflicts."""
        doc_ids = sorted({e.document_id for e in events if e.document_id})
        doc_types = sorted({e.document_type for e in events if e.document_type})

        # Deduplicate repeated/identical events while retaining all SourceReferences
        seen_signatures: dict[tuple[str, str, str], TimelineEvent] = {}
        deduped_events: list[TimelineEvent] = []
        repeated_notes: list[str] = []
        all_refs: list[SourceReference] = []

        for ev in events:
            if ev.source_reference is not None:
                all_refs.append(ev.source_reference)
            dt = parse_valid_date(ev.event_date)
            date_key = dt.strftime("%Y-%m-%d") if dt else (ev.event_date or "")
            sig = (date_key, _norm_text(ev.event_type), _norm_text(ev.description))

            if sig in seen_signatures:
                prev_doc = seen_signatures[sig].document_id or "unknown"
                curr_doc = ev.document_id or "unknown"
                repeated_notes.append(
                    f"Corroborated {ev.event_type} event ('{ev.description}') across documents {prev_doc} and {curr_doc}."
                )
            else:
                seen_signatures[sig] = ev
                deduped_events.append(ev)

        # Detect conflicting event descriptions on the same date and event_type across distinct docs
        ep_conflicts: list[CrossDocumentConflict] = []
        by_date_type: dict[tuple[str, str], list[TimelineEvent]] = defaultdict(list)
        for ev in deduped_events:
            dt = parse_valid_date(ev.event_date)
            if dt is not None and ev.event_type != "document_record":
                by_date_type[(dt.strftime("%Y-%m-%d"), _norm_text(ev.event_type))].append(ev)

        for (date_key, ev_type), group in by_date_type.items():
            if len(group) > 1:
                distinct_docs = sorted({g.document_id for g in group if g.document_id})
                if len(distinct_docs) > 1:
                    ep_conflicts.append(
                        CrossDocumentConflict(
                            conflict_type="clinical_event_conflict",
                            field_name=ev_type,
                            severity=ConflictSeverity.MEDIUM,
                            description=(
                                f"Multiple differing '{ev_type}' descriptions recorded on {date_key} "
                                f"across documents {distinct_docs}: {[g.description for g in group]}."
                            ),
                            document_ids=distinct_docs,
                            source_references=[
                                g.source_reference for g in group if g.source_reference is not None
                            ],
                        )
                    )

        # Link biomarker trends, medications, and health patterns to this episode
        ep_doc_set = set(doc_ids)
        linked_trends = [
            t.biomarker_name
            for t in reconciliation.biomarker_trends
            if any(p.document_id in ep_doc_set for p in t.data_points if p.document_id)
        ]
        linked_meds = [
            m.medication_key
            for m in reconciliation.reconciled_medications
            if any(r.get("document_id") in ep_doc_set for r in m.regimens)
        ]

        ep_patterns = [
            pat for pat in patterns_res.patterns
            if (
                any(ref.document_id in ep_doc_set for ref in pat.source_references if ref.document_id)
                or any(b in linked_trends for b in pat.related_biomarkers)
                or any(m in linked_meds for m in pat.related_medications)
            )
        ]
        linked_pattern_ids = [p.pattern_id for p in ep_patterns]
        ai_observations = [p.explanation for p in ep_patterns] + repeated_notes

        if date_missing:
            start_date, end_date = None, None
            title = "Undated or Uncertain-Date Records"
        else:
            start_date = events[0].event_date
            end_date = events[-1].event_date
            type_label = ", ".join(t.replace("_", " ").title() for t in doc_types) or "Clinical Records"
            title = (
                f"{start_date}: {type_label}"
                if start_date == end_date
                else f"{start_date} to {end_date}: {type_label}"
            )

        return (
            LongitudinalEpisode(
                episode_id=episode_id,
                start_date=start_date,
                end_date=end_date,
                date_missing=date_missing,
                date_uncertain=date_uncertain,
                title=title,
                document_types=doc_types,
                document_ids=doc_ids,
                verified_events=deduped_events,
                duplicate_or_repeated_notes=repeated_notes,
                linked_biomarker_trends=linked_trends,
                linked_medications=linked_meds,
                linked_pattern_ids=linked_pattern_ids,
                ai_observations=ai_observations,
                is_clinical_diagnosis=False,
                source_references=all_refs,
            ),
            ep_conflicts,
        )
