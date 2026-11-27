"""Pydantic schemas for the Multilingual Conversational Health Assistant."""

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from ai_engine.languages import LanguagePreference
from ai_engine.schemas.common import ConfidenceScore, FieldUncertainty, SourceReference


class ConversationTurn(BaseModel):
    """A single turn in a patient-assistant conversation."""

    model_config = ConfigDict(extra="forbid")

    role: str = Field(pattern=r"^(user|assistant)$")
    content: str = Field(min_length=1)
    language_code: Optional[str] = None


class AssistantChatRequest(BaseModel):
    """Input contract for the Multilingual Conversational Health Assistant."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    language: LanguagePreference = Field(
        default_factory=lambda: LanguagePreference(language_code="en")
    )
    verified_records: list[dict[str, Any]] = Field(default_factory=list)
    conversation_history: list[ConversationTurn] = Field(default_factory=list)
    include_reconciliation: bool = True
    include_patterns: bool = True
    include_timeline: bool = True


class AssistantChatResponse(BaseModel):
    """Structured multilingual response grounded in verified patient records."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    response_language: str
    response_language_name: str
    source_language: Optional[str] = None
    detected_source_language: Optional[str] = None
    is_mixed_language: bool = False
    documented_facts: list[str] = Field(default_factory=list)
    ai_observations: list[str] = Field(default_factory=list)
    source_references: list[SourceReference] = Field(default_factory=list)
    source_record_ids: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    conflicting_information: list[str] = Field(default_factory=list)
    uncertainty_flags: list[FieldUncertainty] = Field(default_factory=list)
    insufficient_data: bool = False
    is_clinical_diagnosis: bool = False
    is_clinically_verified: bool = False
    disclaimer: str
    confidence: ConfidenceScore
    provider_used: str
    is_mock: bool = False
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
