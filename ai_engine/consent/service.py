"""Consent-Aware Health Information Sharing service for summaries and Q&A."""

from typing import Optional

from ai_engine.assistant.service import MultilingualHealthAssistant
from ai_engine.consent.enforcer import ConsentEnforcer
from ai_engine.consent.interfaces import ConsentAuthorizationProvider
from ai_engine.languages import validate_language_code
from ai_engine.providers.base import AIProvider
from ai_engine.providers.config import AIProviderConfig
from ai_engine.providers.factory import get_ai_provider
from ai_engine.providers.gemini import GeminiProvider
from ai_engine.schemas.assistant import AssistantChatRequest
from ai_engine.schemas.common import ConfidenceCategory, ConfidenceScore
from ai_engine.schemas.consent import (
    ConsentQuestionRequest,
    ConsentQuestionResponse,
    ConsentShareRequest,
    ConsentShareResponse,
    PermittedDataCategory,
)
from ai_engine.schemas.summary import SummaryResult


class ConsentAwareSharingService:
    """Gates AI summary generation and conversational Q&A behind explicit backend consent."""

    def __init__(
        self,
        provider: Optional[AIProvider] = None,
        provider_config: Optional[AIProviderConfig] = None,
        auth_provider: Optional[ConsentAuthorizationProvider] = None,
        enforcer: Optional[ConsentEnforcer] = None,
    ):
        self.provider = provider or get_ai_provider(provider_config)
        self.enforcer = enforcer or ConsentEnforcer(auth_provider=auth_provider)
        self.assistant = MultilingualHealthAssistant(provider=self.provider)

    async def generate_shared_summary(
        self,
        request: ConsentShareRequest,
    ) -> ConsentShareResponse:
        """Generate a multilingual summary strictly over consent-authorized verified records."""
        resp_lang_code = request.language.response_language or request.language.language_code
        resp_lang = validate_language_code(resp_lang_code)

        evaluation = await self.enforcer.evaluate_and_filter(
            patient_id=request.patient_id,
            recipient_id=request.recipient_id,
            purpose=request.purpose,
            records=request.records,
            consent=request.consent,
            consent_id=request.consent_id,
        )

        if not evaluation.authorized:
            return ConsentShareResponse(
                authorized=False,
                denial_code=evaluation.denial_code,
                denial_reason=evaluation.denial_reason,
                summary=None,
                audit=evaluation.audit,
                response_language=resp_lang.code,
                response_language_name=resp_lang.name,
                is_clinically_verified=False,
            )

        if PermittedDataCategory.SUMMARIES not in set(evaluation.audit.permitted_categories):
            denied_audit = evaluation.audit.model_copy(
                update={
                    "decision": "denied",
                    "denial_code": "CATEGORY_NOT_PERMITTED",
                    "denial_reason": "Access denied: 'summaries' category is not permitted by this consent.",
                    "included_document_ids": [],
                }
            )
            return ConsentShareResponse(
                authorized=False,
                denial_code="CATEGORY_NOT_PERMITTED",
                denial_reason="Access denied: 'summaries' category is not permitted by this consent.",
                summary=None,
                audit=denied_audit,
                response_language=resp_lang.code,
                response_language_name=resp_lang.name,
                is_clinically_verified=False,
            )

        # Call provider ONLY with filtered, authorized records
        if isinstance(self.provider, GeminiProvider):
            raw_summary = await self.provider.generate_summary(
                evaluation.filtered_records,
                language_code=resp_lang.code,
            )
            summary = SummaryResult.model_validate(raw_summary)
        else:
            raw_mock = await self.provider.generate_summary(evaluation.filtered_records)
            summary = SummaryResult(
                insufficient_data=False,
                patient_friendly_summary=raw_mock.get("summary", "Mock summary."),
                doctor_ready_summary=raw_mock.get("summary", "Mock summary."),
                source_record_ids=evaluation.audit.included_document_ids,
                confidence=ConfidenceScore(
                    score=None,
                    source="mock",
                    category=ConfidenceCategory.UNCERTAIN,
                ),
                provider_used="mock",
                response_language=resp_lang.code,
                response_language_name=resp_lang.name,
                is_mock=True,
                is_clinically_verified=False,
            )

        return ConsentShareResponse(
            authorized=True,
            summary=summary,
            audit=evaluation.audit,
            response_language=resp_lang.code,
            response_language_name=resp_lang.name,
            is_clinically_verified=False,
        )

    async def answer_shared_question(
        self,
        request: ConsentQuestionRequest,
    ) -> ConsentQuestionResponse:
        """Answer a question strictly over consent-authorized verified records in the selected language."""
        resp_lang_code = request.language.response_language or request.language.language_code
        resp_lang = validate_language_code(resp_lang_code)

        evaluation = await self.enforcer.evaluate_and_filter(
            patient_id=request.patient_id,
            recipient_id=request.recipient_id,
            purpose=request.purpose,
            records=request.records,
            consent=request.consent,
            consent_id=request.consent_id,
        )

        if not evaluation.authorized:
            return ConsentQuestionResponse(
                authorized=False,
                denial_code=evaluation.denial_code,
                denial_reason=evaluation.denial_reason,
                assistant_response=None,
                audit=evaluation.audit,
                response_language=resp_lang.code,
                response_language_name=resp_lang.name,
                is_clinically_verified=False,
            )

        chat_req = AssistantChatRequest(
            question=request.question,
            language=request.language,
            verified_records=evaluation.filtered_records,
        )
        assistant_resp = await self.assistant.answer_question(chat_req)

        return ConsentQuestionResponse(
            authorized=True,
            assistant_response=assistant_resp,
            audit=evaluation.audit,
            response_language=resp_lang.code,
            response_language_name=resp_lang.name,
            is_clinically_verified=False,
        )
