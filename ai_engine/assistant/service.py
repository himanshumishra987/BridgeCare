"""Multilingual Conversational Health Assistant service."""

from typing import Any, Optional

from ai_engine.languages import (
    LanguagePreference,
    detect_source_language,
    validate_language_code,
)
from ai_engine.patterns.engine import HealthPatternAnalyzer
from ai_engine.providers.base import AIProvider
from ai_engine.providers.config import AIProviderConfig
from ai_engine.providers.factory import get_ai_provider
from ai_engine.providers.gemini import GeminiProvider
from ai_engine.providers.mock import MockProvider
from ai_engine.reconciliation.engine import CrossDocumentReconciler
from ai_engine.schemas.assistant import (
    AssistantChatRequest,
    AssistantChatResponse,
)
from ai_engine.schemas.common import ConfidenceCategory, ConfidenceScore, FieldUncertainty
from ai_engine.timeline.builder import LongitudinalTimelineBuilder


class MultilingualHealthAssistant:
    """Grounded multilingual conversational assistant over human-verified patient records.

    Uses CrossDocumentReconciler, HealthPatternAnalyzer, and LongitudinalTimelineBuilder
    as factual context, and enforces the user's selected response language over the
    question language.
    """

    def __init__(
        self,
        provider: Optional[AIProvider] = None,
        provider_config: Optional[AIProviderConfig] = None,
        reconciler: Optional[CrossDocumentReconciler] = None,
        pattern_analyzer: Optional[HealthPatternAnalyzer] = None,
        timeline_builder: Optional[LongitudinalTimelineBuilder] = None,
    ):
        self.provider = provider or get_ai_provider(provider_config)
        self.reconciler = reconciler or CrossDocumentReconciler()
        self.pattern_analyzer = pattern_analyzer or HealthPatternAnalyzer(self.reconciler)
        self.timeline_builder = timeline_builder or LongitudinalTimelineBuilder(
            self.reconciler, self.pattern_analyzer
        )

    async def ask(
        self,
        question: str,
        verified_records: list[dict[str, Any]],
        language_code: str = "en",
        source_language: Optional[str] = None,
    ) -> AssistantChatResponse:
        """Convenience wrapper for asking a question with explicit language parameters."""
        request = AssistantChatRequest(
            question=question,
            language=LanguagePreference(
                language_code=language_code,
                source_language=source_language,
                response_language=language_code,
            ),
            verified_records=verified_records,
        )
        return await self.answer_question(request)

    async def answer_question(
        self,
        request: AssistantChatRequest,
    ) -> AssistantChatResponse:
        """Answer a patient health question grounded strictly in verified records."""
        resp_lang_code = request.language.response_language or request.language.language_code
        resp_lang = validate_language_code(resp_lang_code)

        # Automatic source-language detection (explicit source_language always takes precedence)
        detection = detect_source_language(request.question)
        effective_source_lang = request.language.source_language or detection.detected_language
        detection_uncertainties: list[FieldUncertainty] = []
        if request.language.source_language is None and (detection.uncertain or detection.is_mixed_language) and detection.reason:
            detection_uncertainties.append(
                FieldUncertainty(
                    field_name="source_language",
                    reason=detection.reason,
                )
            )

        # 1. Enforce strict human-verification gating (rejects pending_review/rejected)
        reconciliation = self.reconciler.reconcile(request.verified_records)

        # 2. Guard against empty or unavailable verified medical context
        if reconciliation.insufficient_data:
            return AssistantChatResponse(
                answer=(
                    f"[{resp_lang.name}] Insufficient verified medical records are available "
                    "to answer this question. Please upload and verify your health records first."
                ),
                response_language=resp_lang.code,
                response_language_name=resp_lang.name,
                source_language=effective_source_lang,
                detected_source_language=detection.detected_language,
                is_mixed_language=detection.is_mixed_language,
                documented_facts=[],
                ai_observations=[],
                source_references=[],
                source_record_ids=[],
                missing_information=["No human-verified medical records available."],
                conflicting_information=[],
                uncertainty_flags=[
                    FieldUncertainty(
                        field_name="verified_records",
                        reason="No human-verified records supplied for conversational context.",
                    )
                ] + detection_uncertainties,
                insufficient_data=True,
                is_clinical_diagnosis=False,
                is_clinically_verified=False,
                disclaimer=(
                    "Observational assistant only. Not a clinical diagnosis or medical advice."
                ),
                confidence=ConfidenceScore(
                    score=None,
                    source="bridgecare:assistant",
                    category=ConfidenceCategory.UNCERTAIN,
                ),
                provider_used="mock" if isinstance(self.provider, MockProvider) else "gemini",
                is_mock=isinstance(self.provider, MockProvider),
            )

        # 3. Assemble grounded context from existing intelligence modules
        context_payload: dict[str, Any] = {
            "source_record_ids": reconciliation.source_record_ids,
            "verified_records": request.verified_records,
        }
        if request.include_reconciliation:
            context_payload["reconciliation"] = reconciliation.model_dump(mode="json")

        patterns_res = None
        if request.include_patterns or request.include_timeline:
            patterns_res = self.pattern_analyzer.analyze_reconciliation(reconciliation)
            if request.include_patterns:
                context_payload["health_patterns"] = patterns_res.model_dump(mode="json")

        if request.include_timeline:
            timeline_res = self.timeline_builder.build_from_reconciliation(
                reconciliation=reconciliation,
                pattern_result=patterns_res,
                raw_records=request.verified_records,
            )
            context_payload["longitudinal_timeline"] = timeline_res.model_dump(mode="json")

        # 4. Explicit mock provider mode (offline development only)
        if isinstance(self.provider, MockProvider):
            return AssistantChatResponse(
                answer=(
                    f"[Mock - {resp_lang.name}] Verified records ({len(request.verified_records)}) "
                    "received. Mock mode does not generate live multilingual responses."
                ),
                response_language=resp_lang.code,
                response_language_name=resp_lang.name,
                source_language=effective_source_lang,
                detected_source_language=detection.detected_language,
                is_mixed_language=detection.is_mixed_language,
                documented_facts=[],
                ai_observations=["Mock assistant response only."],
                source_references=[],
                source_record_ids=reconciliation.source_record_ids,
                missing_information=[],
                conflicting_information=[c.description for c in reconciliation.conflicts],
                uncertainty_flags=list(reconciliation.uncertainty_flags) + detection_uncertainties,
                insufficient_data=False,
                is_clinical_diagnosis=False,
                is_clinically_verified=False,
                disclaimer="Mock assistant response only. Not a clinical diagnosis.",
                confidence=ConfidenceScore(
                    score=None,
                    source="mock",
                    category=ConfidenceCategory.UNCERTAIN,
                ),
                provider_used="mock",
                is_mock=True,
            )

        # 5. Live / GeminiProvider execution (no silent fallback to mock)
        if isinstance(self.provider, GeminiProvider):
            raw_resp = await self.provider.answer_health_question(
                question=request.question,
                context_payload=context_payload,
                response_language_code=resp_lang.code,
                source_language_code=effective_source_lang,
                conversation_history=[t.model_dump() for t in request.conversation_history],
            )
            raw_resp["detected_source_language"] = detection.detected_language
            raw_resp["is_mixed_language"] = detection.is_mixed_language
            if detection_uncertainties:
                raw_resp["uncertainty_flags"] = list(raw_resp.get("uncertainty_flags", [])) + [
                    u.model_dump() for u in detection_uncertainties
                ]
            # Guarantee reconciliation conflicts and record missing_fields are surfaced
            existing_conflicts = list(raw_resp.get("conflicting_information", []))
            for conflict in reconciliation.conflicts:
                if conflict.description not in existing_conflicts:
                    existing_conflicts.append(conflict.description)
            raw_resp["conflicting_information"] = existing_conflicts

            existing_missing = list(raw_resp.get("missing_information", []))
            for rec in request.verified_records:
                for mf in rec.get("missing_fields") or []:
                    if isinstance(mf, str) and mf.strip() and mf.strip() not in existing_missing:
                        existing_missing.append(mf.strip())
            raw_resp["missing_information"] = existing_missing

            return AssistantChatResponse.model_validate(raw_resp)

        raise NotImplementedError(
            f"Provider '{type(self.provider).__name__}' does not support multilingual conversational Q&A."
        )
