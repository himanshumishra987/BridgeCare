"""Gemini-powered medical document classification and information extraction provider."""

import asyncio
import json
import logging
from typing import Any, Optional

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_engine.languages import validate_language_code
from ai_engine.providers.base import AIProvider
from ai_engine.providers.config import AIProviderConfig
from ai_engine.providers.exceptions import (
    ProviderAPIError,
    ProviderConfigurationError,
    ProviderResponseError,
    ProviderTimeoutError,
    UnverifiedRecordError,
)
from ai_engine.schemas.classification import (
    ClassificationInput,
    ClassificationResult,
    DocumentType,
)
from ai_engine.schemas.common import (
    ConfidenceCategory,
    ConfidenceScore,
    FieldUncertainty,
    SourceReference,
)
from ai_engine.schemas.extraction import (
    ExtractedBiomarker,
    ExtractedClinicalEvent,
    ExtractedMedication,
    ExtractionResult,
)
from ai_engine.schemas.summary import (
    SummaryResult,
    VerifiedRecordInput,
)

logger = logging.getLogger(__name__)

_CLASSIFICATION_SYSTEM_INSTRUCTION = """You are a medical document classification component for BridgeCare.
Classify the provided document text into exactly ONE canonical category:
- lab_report: Laboratory test results, blood work, pathology, radiology/imaging reports.
- prescription: Medication prescriptions, Rx orders, dosage schedules.
- discharge_summary: Inpatient hospital admission and discharge summaries.
- clinical_note: Doctor's clinical notes, outpatient consultation summaries, progress notes, referral letters. (A consultation summary MUST be classified as clinical_note.)
- ayush_record: Ayurveda, Yoga, Naturopathy, Unani, Siddha, or Homeopathy records/prescriptions.
- insurance_doc: Health insurance policies, claims, pre-authorizations, medical billing/EOB statements.
- other: Any document that does not fit the above categories or lacks sufficient context.

Safety & Uncertainty Rules:
1. Do NOT invent patient details, clinical facts, or medical interpretations.
2. Do NOT claim that this classification is clinically validated.
3. If the document is ambiguous, mixed, or lacks sufficient information, use confidence_category "uncertain" or "low", lower confidence_score accordingly, and explain the ambiguity in uncertainty_reasons.

Return ONLY a valid JSON object matching this exact schema:
{
  "document_type": "<one of: lab_report, prescription, discharge_summary, clinical_note, ayush_record, insurance_doc, other>",
  "raw_document_type": "<optional specific subtype string or null>",
  "confidence_score": <float between 0.0 and 1.0>,
  "confidence_category": "<one of: high, medium, low, uncertain>",
  "uncertainty_reasons": ["<string>"]
}"""

_EXTRACTION_SYSTEM_INSTRUCTION = """You are a structured medical information extraction component for BridgeCare.
Extract ONLY explicitly documented facts from the provided medical document text.

Strict Accuracy, Provenance, and Safety Rules:
1. NEVER invent, guess, or hallucinate missing values, dates, patient names, doctor names, hospital/lab names, medication dosages, frequencies, routes, or instructions.
2. Preserve original reported values (`value` as exact string) and original `unit` verbatim. Do NOT convert units.
3. Do NOT force irrelevant fields into every document type (for example, leave `biomarkers` empty for a prescription or insurance document if no lab values are documented).
4. Extract diagnoses, symptoms/complaints, procedures, hospital admissions/discharges, and relevant insurance/record events into `clinical_events` when explicitly documented.
5. Distinguish explicitly documented facts from ambiguous, illegible, or conflicting data: record any missing, ambiguous, or conflicting fields in `missing_fields` and `uncertainty_flags`.
6. Attach `source_reference` (`page_number` >= 1, verbatim `excerpt`, and `field_name`) wherever supported by the text. If page markers like `[Page 2]` appear, use that page number; otherwise default to 1. If no verbatim excerpt exists, omit `source_reference` (`null`).
7. Do NOT mark any extracted data as clinically verified, and do NOT provide medical diagnoses or treatment recommendations.

Return ONLY a valid JSON object matching this exact structure:
{
  "document_date": "<string or null>",
  "hospital_or_lab_name": "<string or null>",
  "doctor_name": "<string or null>",
  "patient_name": "<string or null>",
  "biomarkers": [
    {
      "name": "<string>",
      "value": "<exact reported string>",
      "numeric_value": <float or null>,
      "unit": "<string or null>",
      "reference_range": "<string or null>",
      "abnormal_flag": "<string or null>",
      "confidence_score": <float 0.0-1.0 or null>,
      "confidence_category": "<high|medium|low|uncertain>",
      "source_reference": {"page_number": 1, "excerpt": "<verbatim snippet>", "field_name": "<string or null>"}
    }
  ],
  "medications": [
    {
      "brand_name": "<string or null>",
      "generic_ingredients": ["<string>"],
      "strength": "<string or null>",
      "dosage": "<string or null>",
      "frequency": "<string or null>",
      "duration": "<string or null>",
      "instructions": "<string or null>",
      "confidence_score": <float 0.0-1.0 or null>,
      "confidence_category": "<high|medium|low|uncertain>",
      "source_reference": {"page_number": 1, "excerpt": "<verbatim snippet>", "field_name": "<string or null>"}
    }
  ],
  "clinical_events": [
    {
      "event_type": "<string: e.g. diagnosis, symptom, procedure, admission, discharge, consultation, claim>",
      "description": "<string>",
      "event_date": "<string or null>",
      "confidence_score": <float 0.0-1.0 or null>,
      "confidence_category": "<high|medium|low|uncertain>",
      "source_reference": {"page_number": 1, "excerpt": "<verbatim snippet>", "field_name": "<string or null>"}
    }
  ],
  "missing_fields": ["<string>"],
  "uncertainty_flags": [
    {
      "field_name": "<string>",
      "reason": "<string>",
      "source_reference": {"page_number": 1, "excerpt": "<verbatim snippet>", "field_name": "<string or null>"}
    }
  ],
  "overall_confidence_score": <float 0.0-1.0 or null>,
  "overall_confidence_category": "<high|medium|low|uncertain>"
}"""

_SUMMARY_SYSTEM_INSTRUCTION = """You are a grounded medical summary generator for BridgeCare.
Generate two summaries strictly from the supplied human-verified medical records.

Strict Grounding & Clinical Safety Rules:
1. Use ONLY the supplied human-verified records. NEVER invent diagnoses, symptoms, medicines, dosages, dates, or laboratory results.
2. Do NOT infer a disease or diagnosis from an isolated abnormal laboratory value.
3. Do NOT provide treatment recommendations or suggest medication changes.
4. Do NOT present the summary as a clinical diagnosis.
5. Preserve original reported values and units verbatim.
6. Only describe laboratory trends when comparable values exist across multiple dates/records.
7. Never conceal conflicting records; explicitly list conflicts in `conflicting_information` and `uncertainty_flags`.
8. Include `source_references` using the exact `document_id`, `page_number`, and verbatim `excerpt` from the supplied records. Do NOT fabricate excerpts or document IDs.

Return ONLY a valid JSON object matching this exact structure:
{
  "patient_friendly_summary": "<clear, accessible explanation of the records, history, medications, lab findings, dates/chronology, and missing/conflicting info>",
  "doctor_ready_summary": "<concise structured clinical snapshot with diagnoses/events, medication history, lab findings/trends where comparable, source citations, and explicit data gaps/conflicts>",
  "key_findings": ["<concise factual finding grounded in the records>"],
  "source_references": [
    {"document_id": "<string or null>", "page_number": 1, "excerpt": "<verbatim snippet from supplied records>", "field_name": "<string or null>"}
  ],
  "missing_information": ["<string>"],
  "conflicting_information": ["<string>"],
  "uncertainty_flags": [
    {"field_name": "<string>", "reason": "<string>", "source_reference": null}
  ],
  "confidence_score": <float 0.0-1.0 or null>,
  "confidence_category": "<high|medium|low|uncertain>"
}"""


_CONVERSATION_SYSTEM_INSTRUCTION = """You are BridgeCare's Multilingual Conversational Health Assistant.
Answer the patient's question strictly using ONLY the supplied human-verified patient health context.

Critical Language & Safety Rules:
1. ALWAYS write your answer, documented_facts, ai_observations, missing_information, conflicting_information, and disclaimer in the explicitly requested Response Language, EVEN IF the user's question or source documents are in a different language.
2. NEVER invent diagnoses, test results, medication instructions, dosages, or medical history.
3. Preserve all numerical values, units, dates, medicine names, and dosage instructions exactly as documented.
4. Clearly distinguish documented facts (`documented_facts`) from AI-generated observations (`ai_observations`), and distinguish original document statements from translated explanations.
5. Refuse to provide unsupported medical conclusions, clinical diagnoses, or recommendations to change/stop medications.
6. If the patient's question is unrelated to the supplied verified records or asks for unsupported medical advice, state clearly that the supplied records do not contain evidence for that question, leave `documented_facts` empty (`[]`), and set `confidence_category` to `"uncertain"`.
7. Surface any missing, ambiguous, or conflicting information explicitly without silently choosing one conflicting record over another.
8. Include `source_references` using the exact `document_id`, `page_number`, and verbatim `excerpt` from the supplied context. If multiple documents support a claim, include a `source_reference` for EACH supporting document.

Return ONLY a valid JSON object matching this exact structure:
{
  "answer": "<clear, empathetic, grounded response in the requested Response Language>",
  "documented_facts": ["<fact grounded in verified records, in Response Language while preserving exact values/units/med names>"],
  "ai_observations": ["<non-diagnostic observational note in Response Language>"],
  "source_references": [
    {"document_id": "<string or null>", "page_number": 1, "excerpt": "<verbatim snippet from supplied records>", "field_name": "<string or null>"}
  ],
  "missing_information": ["<string in Response Language>"],
  "conflicting_information": ["<string in Response Language>"],
  "uncertainty_flags": [
    {"field_name": "<string>", "reason": "<string in Response Language>", "source_reference": null}
  ],
  "disclaimer": "<non-diagnostic medical safety disclaimer in Response Language>",
  "confidence_score": <float 0.0-1.0 or null>,
  "confidence_category": "<high|medium|low|uncertain>"
}"""


class _GeminiConversationPayload(BaseModel):
    """Internal schema to validate raw conversational JSON returned by Gemini."""

    model_config = ConfigDict(extra="ignore")

    answer: str = Field(min_length=1)
    documented_facts: list[str] = Field(default_factory=list)
    ai_observations: list[str] = Field(default_factory=list)
    source_references: list[_GeminiSourceRefPayload] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    conflicting_information: list[str] = Field(default_factory=list)
    uncertainty_flags: list[_GeminiFieldUncertaintyPayload] = Field(default_factory=list)
    disclaimer: str = (
        "This information is based only on your verified records and is not a medical diagnosis."
    )
    confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence_category: ConfidenceCategory = ConfidenceCategory.UNCERTAIN


class _GeminiClassificationPayload(BaseModel):
    """Internal schema to validate raw classification JSON returned by Gemini."""

    model_config = ConfigDict(extra="ignore")

    document_type: DocumentType
    raw_document_type: Optional[str] = None
    confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence_category: ConfidenceCategory = ConfidenceCategory.UNCERTAIN
    uncertainty_reasons: list[str] = Field(default_factory=list)


class _GeminiSourceRefPayload(BaseModel):
    """Internal schema for source references returned by Gemini."""

    model_config = ConfigDict(extra="ignore")

    document_id: Optional[str] = None
    page_number: int = 1
    excerpt: Optional[str] = None
    field_name: Optional[str] = None


class _GeminiBiomarkerPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1)
    value: str
    numeric_value: Optional[float] = None
    unit: Optional[str] = None
    reference_range: Optional[str] = None
    abnormal_flag: Optional[str] = None
    confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence_category: Optional[ConfidenceCategory] = None
    source_reference: Optional[_GeminiSourceRefPayload] = None


class _GeminiMedicationPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    brand_name: Optional[str] = None
    generic_ingredients: list[str] = Field(default_factory=list)
    strength: Optional[str] = None
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    duration: Optional[str] = None
    instructions: Optional[str] = None
    confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence_category: Optional[ConfidenceCategory] = None
    source_reference: Optional[_GeminiSourceRefPayload] = None


class _GeminiClinicalEventPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_type: str = Field(min_length=1)
    description: str = Field(min_length=1)
    event_date: Optional[str] = None
    confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence_category: Optional[ConfidenceCategory] = None
    source_reference: Optional[_GeminiSourceRefPayload] = None


class _GeminiFieldUncertaintyPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    field_name: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    source_reference: Optional[_GeminiSourceRefPayload] = None


class _GeminiExtractionPayload(BaseModel):
    """Internal schema to validate raw extraction JSON returned by Gemini."""

    model_config = ConfigDict(extra="ignore")

    document_date: Optional[str] = None
    hospital_or_lab_name: Optional[str] = None
    doctor_name: Optional[str] = None
    patient_name: Optional[str] = None

    biomarkers: list[_GeminiBiomarkerPayload] = Field(default_factory=list)
    medications: list[_GeminiMedicationPayload] = Field(default_factory=list)
    clinical_events: list[_GeminiClinicalEventPayload] = Field(default_factory=list)

    missing_fields: list[str] = Field(default_factory=list)
    uncertainty_flags: list[_GeminiFieldUncertaintyPayload] = Field(default_factory=list)

    overall_confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    overall_confidence_category: ConfidenceCategory = ConfidenceCategory.UNCERTAIN


class _GeminiSummaryPayload(BaseModel):
    """Internal schema to validate raw summary JSON returned by Gemini."""

    model_config = ConfigDict(extra="ignore")

    patient_friendly_summary: str = Field(min_length=1)
    doctor_ready_summary: str = Field(min_length=1)
    key_findings: list[str] = Field(default_factory=list)
    source_references: list[_GeminiSourceRefPayload] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    conflicting_information: list[str] = Field(default_factory=list)
    uncertainty_flags: list[_GeminiFieldUncertaintyPayload] = Field(default_factory=list)
    confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence_category: ConfidenceCategory = ConfidenceCategory.UNCERTAIN


class GeminiProvider(AIProvider):
    """Production Gemini AI provider using the official google-genai SDK."""

    MIN_MEANINGFUL_ALNUM_CHARS = 10

    def __init__(
        self,
        config: Optional[AIProviderConfig] = None,
        client: Optional[genai.Client] = None,
    ):
        self.config = config or AIProviderConfig()

        if not self.config.gemini_model or not self.config.gemini_model.strip():
            raise ProviderConfigurationError(
                "GEMINI_MODEL must be configured and non-empty.",
                provider="gemini",
            )

        if client is not None:
            self._client = client
        else:
            api_key_secret = self.config.gemini_api_key
            api_key = api_key_secret.get_secret_value().strip() if api_key_secret else ""
            if not api_key:
                raise ProviderConfigurationError(
                    "GEMINI_API_KEY is required when using the Gemini provider.",
                    provider="gemini",
                )
            self._client = genai.Client(api_key=api_key)

    @property
    def _model_source(self) -> str:
        return f"gemini:{self.config.gemini_model}"

    async def _generate_json_with_retry(
        self,
        contents: str,
        system_instruction: str,
        operation: str,
    ) -> dict[str, Any]:
        """Execute a Gemini generate_content call with bounded timeouts, retries, and JSON parsing."""
        gen_config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            temperature=0.0,
        )

        max_attempts = 1 + self.config.gemini_max_retries
        last_error: Optional[Exception] = None

        for attempt in range(max_attempts):
            try:
                response = await asyncio.wait_for(
                    self._client.aio.models.generate_content(
                        model=self.config.gemini_model,
                        contents=contents,
                        config=gen_config,
                    ),
                    timeout=self.config.gemini_timeout_seconds,
                )
                return self._parse_json_object(getattr(response, "text", None))

            except (asyncio.TimeoutError, TimeoutError):
                last_error = ProviderTimeoutError(
                    f"Gemini {operation} timed out after {self.config.gemini_timeout_seconds}s.",
                    provider="gemini",
                )
                logger.warning(
                    "Gemini %s timeout on attempt %d/%d",
                    operation,
                    attempt + 1,
                    max_attempts,
                )

            except genai_errors.APIError as e:
                status_code = getattr(e, "code", None)
                is_retryable = status_code in (429, 500, 502, 503, 504)
                last_error = ProviderAPIError(
                    message=f"Gemini API request failed (status={status_code}).",
                    provider="gemini",
                    status_code=status_code,
                    retryable=is_retryable,
                )
                logger.warning(
                    "Gemini %s API error (status=%s, retryable=%s) on attempt %d/%d",
                    operation,
                    status_code,
                    is_retryable,
                    attempt + 1,
                    max_attempts,
                )
                if not is_retryable:
                    raise last_error from e

            except ProviderResponseError:
                raise

            except Exception as e:
                logger.warning("Unexpected Gemini %s error: %s", operation, type(e).__name__)
                raise ProviderAPIError(
                    message=f"Unexpected Gemini provider failure ({type(e).__name__}).",
                    provider="gemini",
                    retryable=False,
                ) from e

            if attempt < max_attempts - 1:
                delay = self.config.gemini_retry_base_delay_seconds * (2 ** attempt)
                if delay > 0:
                    await asyncio.sleep(delay)

        assert last_error is not None
        raise last_error

    @staticmethod
    def _parse_json_object(raw_text: Optional[str]) -> dict[str, Any]:
        """Parse raw model text into a JSON dict, raising ProviderResponseError on failure."""
        if not raw_text or not raw_text.strip():
            raise ProviderResponseError(
                "Gemini returned an empty response.",
                provider="gemini",
            )

        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()

        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ProviderResponseError(
                "Gemini returned malformed JSON.",
                provider="gemini",
            ) from e

        if not isinstance(payload, dict):
            raise ProviderResponseError(
                "Gemini JSON response must be a JSON object.",
                provider="gemini",
            )
        return payload

    async def classify_document(self, document_text: str) -> dict[str, Any]:
        """Classify a medical document asynchronously using the configured Gemini model."""
        ClassificationInput(document_text=document_text)

        alnum_count = sum(1 for c in document_text if c.isalnum())
        if alnum_count < self.MIN_MEANINGFUL_ALNUM_CHARS:
            uncertain_result = ClassificationResult(
                document_type=DocumentType.OTHER,
                raw_document_type=None,
                confidence=ConfidenceScore(
                    score=None,
                    source=self._model_source,
                    category=ConfidenceCategory.UNCERTAIN,
                ),
                uncertainty_flags=[
                    FieldUncertainty(
                        field_name="document_type",
                        reason="Insufficient document text to classify reliably.",
                    )
                ],
                provider_used="gemini",
                is_mock=False,
            )
            return uncertain_result.model_dump()

        payload = await self._generate_json_with_retry(
            contents=document_text,
            system_instruction=_CLASSIFICATION_SYSTEM_INSTRUCTION,
            operation="classification",
        )
        return self._validate_classification_payload(payload)

    def _validate_classification_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate parsed classification JSON against BridgeCare schemas."""
        try:
            parsed = _GeminiClassificationPayload.model_validate(payload)
        except ValidationError as e:
            raise ProviderResponseError(
                "Gemini response failed classification schema validation.",
                provider="gemini",
            ) from e

        uncertainty_flags = [
            FieldUncertainty(field_name="document_type", reason=reason.strip())
            for reason in parsed.uncertainty_reasons
            if isinstance(reason, str) and reason.strip()
        ]

        result = ClassificationResult(
            document_type=parsed.document_type,
            raw_document_type=parsed.raw_document_type,
            confidence=ConfidenceScore(
                score=parsed.confidence_score,
                source=self._model_source,
                category=parsed.confidence_category,
            ),
            uncertainty_flags=uncertainty_flags,
            provider_used="gemini",
            is_mock=False,
        )
        return result.model_dump()

    async def extract_information(
        self,
        document_text: str,
        document_type: str,
    ) -> dict[str, Any]:
        """Extract structured medical information asynchronously using the configured Gemini model."""
        ClassificationInput(document_text=document_text)
        doc_type = DocumentType(document_type)

        alnum_count = sum(1 for c in document_text if c.isalnum())
        if alnum_count < self.MIN_MEANINGFUL_ALNUM_CHARS:
            uncertain_result = ExtractionResult(
                document_type=doc_type,
                missing_fields=["document_text"],
                uncertainty_flags=[
                    FieldUncertainty(
                        field_name="document_text",
                        reason="Insufficient document text to extract structured medical information.",
                    )
                ],
                overall_confidence=ConfidenceScore(
                    score=None,
                    source=self._model_source,
                    category=ConfidenceCategory.UNCERTAIN,
                ),
            )
            return uncertain_result.model_dump()

        user_prompt = (
            f"Document Category: {doc_type.value}\n\n"
            f"Document Text:\n{document_text}"
        )
        payload = await self._generate_json_with_retry(
            contents=user_prompt,
            system_instruction=_EXTRACTION_SYSTEM_INSTRUCTION,
            operation="extraction",
        )
        return self._validate_extraction_payload(payload, doc_type)

    def _to_source_reference(
        self,
        raw_ref: Optional[_GeminiSourceRefPayload],
        default_field: Optional[str] = None,
    ) -> Optional[SourceReference]:
        """Convert parsed source reference into a valid SourceReference or None if empty."""
        if raw_ref is None or not raw_ref.excerpt or not raw_ref.excerpt.strip():
            return None
        page_num = raw_ref.page_number if raw_ref.page_number >= 1 else 1
        return SourceReference(
            document_id=raw_ref.document_id,
            page_number=page_num,
            excerpt=raw_ref.excerpt.strip(),
            field_name=raw_ref.field_name or default_field,
        )

    def _to_confidence_score(
        self,
        score: Optional[float],
        category: Optional[ConfidenceCategory],
    ) -> Optional[ConfidenceScore]:
        """Build a ConfidenceScore with explicit Gemini provenance."""
        if score is None and category is None:
            return None
        return ConfidenceScore(
            score=score,
            source=self._model_source,
            category=category or ConfidenceCategory.UNCERTAIN,
        )

    def _validate_extraction_payload(
        self,
        payload: dict[str, Any],
        doc_type: DocumentType,
    ) -> dict[str, Any]:
        """Validate parsed extraction JSON against ExtractionResult schema."""
        try:
            parsed = _GeminiExtractionPayload.model_validate(payload)
        except ValidationError as e:
            raise ProviderResponseError(
                "Gemini response failed extraction schema validation.",
                provider="gemini",
            ) from e

        biomarkers = [
            ExtractedBiomarker(
                name=b.name.strip(),
                value=b.value,
                numeric_value=b.numeric_value,
                unit=b.unit,
                reference_range=b.reference_range,
                abnormal_flag=b.abnormal_flag,
                source_reference=self._to_source_reference(b.source_reference, b.name.strip()),
                confidence=self._to_confidence_score(b.confidence_score, b.confidence_category),
            )
            for b in parsed.biomarkers
        ]

        medications = [
            ExtractedMedication(
                brand_name=m.brand_name,
                generic_ingredients=[g.strip() for g in m.generic_ingredients if g and g.strip()],
                strength=m.strength,
                dosage=m.dosage,
                frequency=m.frequency,
                duration=m.duration,
                instructions=m.instructions,
                source_reference=self._to_source_reference(
                    m.source_reference,
                    m.brand_name or (m.generic_ingredients[0] if m.generic_ingredients else "medication"),
                ),
                confidence=self._to_confidence_score(m.confidence_score, m.confidence_category),
            )
            for m in parsed.medications
        ]

        clinical_events = [
            ExtractedClinicalEvent(
                event_type=ev.event_type.strip(),
                description=ev.description.strip(),
                event_date=ev.event_date,
                source_reference=self._to_source_reference(ev.source_reference, ev.event_type.strip()),
                confidence=self._to_confidence_score(ev.confidence_score, ev.confidence_category),
            )
            for ev in parsed.clinical_events
        ]

        uncertainty_flags = [
            FieldUncertainty(
                field_name=u.field_name.strip(),
                reason=u.reason.strip(),
                source_reference=self._to_source_reference(u.source_reference, u.field_name.strip()),
            )
            for u in parsed.uncertainty_flags
        ]

        result = ExtractionResult(
            document_type=doc_type,
            document_date=parsed.document_date,
            hospital_or_lab_name=parsed.hospital_or_lab_name,
            doctor_name=parsed.doctor_name,
            patient_name=parsed.patient_name,
            biomarkers=biomarkers,
            medications=medications,
            clinical_events=clinical_events,
            missing_fields=[f.strip() for f in parsed.missing_fields if f and f.strip()],
            uncertainty_flags=uncertainty_flags,
            overall_confidence=ConfidenceScore(
                score=parsed.overall_confidence_score,
                source=self._model_source,
                category=parsed.overall_confidence_category,
            ),
        )
        return result.model_dump()

    async def generate_summary(
        self,
        verified_records: list[dict[str, Any]],
        language_code: str = "en",
    ) -> dict[str, Any]:
        """Generate grounded patient-friendly and doctor-ready summaries in the selected language."""
        lang_info = validate_language_code(language_code)

        if not isinstance(verified_records, list):
            raise UnverifiedRecordError(
                "verified_records must be a list of human-verified record dictionaries.",
                provider="gemini",
            )

        if not verified_records:
            return self._insufficient_summary_result(
                ["No human-verified medical records supplied."],
                language_code=lang_info.code,
                language_name=lang_info.name,
            )

        validated_records: list[VerifiedRecordInput] = []
        for idx, rec in enumerate(verified_records):
            if not isinstance(rec, dict):
                raise UnverifiedRecordError(
                    f"Record at index {idx} must be a dictionary with an approved verification_status.",
                    provider="gemini",
                )
            try:
                validated_records.append(VerifiedRecordInput.model_validate(rec))
            except ValidationError as e:
                raise UnverifiedRecordError(
                    f"Record at index {idx} rejected: only explicitly human-verified records "
                    "('verified' or 'edited_verified') are permitted for summary generation.",
                    provider="gemini",
                ) from e

        has_clinical_content = any(
            r.biomarkers or r.medications or r.clinical_events or r.document_date or r.hospital_or_lab_name
            for r in validated_records
        )
        if not has_clinical_content:
            return self._insufficient_summary_result(
                ["Verified records contain no documented clinical findings, medications, or metadata."],
                language_code=lang_info.code,
                language_name=lang_info.name,
            )

        serialized_records = json.dumps(
            [r.model_dump(mode="json") for r in validated_records],
            ensure_ascii=False,
        )
        user_prompt = (
            f"Target Output Language: {lang_info.name} ({lang_info.code})\n"
            "Write patient_friendly_summary, doctor_ready_summary, key_findings, "
            "missing_information, and conflicting_information in the Target Output Language. "
            "Preserve all original numbers, units, dates, medicine names, dosage instructions, "
            "and verbatim source_reference excerpts unchanged.\n\n"
            f"Human-Verified Medical Records:\n{serialized_records}"
        )

        payload = await self._generate_json_with_retry(
            contents=user_prompt,
            system_instruction=_SUMMARY_SYSTEM_INSTRUCTION,
            operation="summary_generation",
        )
        return self._validate_summary_payload(
            payload,
            validated_records,
            verified_records,
            language_code=lang_info.code,
            language_name=lang_info.name,
        )

    def _insufficient_summary_result(
        self,
        missing_reasons: list[str],
        language_code: str = "en",
        language_name: str = "English",
    ) -> dict[str, Any]:
        """Return a structured insufficient-data SummaryResult without fabricating content."""
        return SummaryResult(
            insufficient_data=True,
            patient_friendly_summary=(
                "Insufficient verified medical information is currently available to generate a summary."
            ),
            doctor_ready_summary=(
                "Insufficient verified clinical data. No summary generated from unverified or empty records."
            ),
            key_findings=[],
            source_references=[],
            source_record_ids=[],
            missing_information=missing_reasons,
            conflicting_information=[],
            uncertainty_flags=[
                FieldUncertainty(
                    field_name="verified_records",
                    reason=missing_reasons[0] if missing_reasons else "Insufficient verified records.",
                )
            ],
            confidence=ConfidenceScore(
                score=None,
                source=self._model_source,
                category=ConfidenceCategory.UNCERTAIN,
            ),
            provider_used="gemini",
            response_language=language_code,
            response_language_name=language_name,
            is_mock=False,
            is_clinically_verified=False,
        ).model_dump()

    @staticmethod
    def _collect_known_pages_by_doc(records: list[dict[str, Any]]) -> dict[str, set[int]]:
        """Collect known page numbers per document_id from supplied records' source references."""
        pages_by_doc: dict[str, set[int]] = {}
        for rec in records:
            if not isinstance(rec, dict):
                continue
            default_doc_id = rec.get("document_id")
            for section in ("biomarkers", "medications", "clinical_events", "uncertainty_flags"):
                for item in rec.get(section) or []:
                    if not isinstance(item, dict):
                        continue
                    ref = item.get("source_reference")
                    if isinstance(ref, dict) and isinstance(ref.get("page_number"), int):
                        doc_id = ref.get("document_id") or default_doc_id
                        if doc_id:
                            pages_by_doc.setdefault(str(doc_id), set()).add(ref["page_number"])
        return pages_by_doc

    def _verify_grounded_references(
        self,
        raw_refs: list[_GeminiSourceRefPayload],
        valid_doc_ids: set[str],
        known_pages_by_doc: dict[str, set[int]],
        normalized_corpus: str,
        uncertainty_flags: list[FieldUncertainty],
    ) -> list[SourceReference]:
        """Verify model-cited SourceReferences against supplied documents, pages, and excerpts."""
        verified_refs: list[SourceReference] = []
        for raw_ref in raw_refs:
            ref = self._to_source_reference(raw_ref)
            if ref is None:
                continue

            if ref.document_id and valid_doc_ids and ref.document_id not in valid_doc_ids:
                uncertainty_flags.append(
                    FieldUncertainty(
                        field_name=ref.field_name or "source_reference",
                        reason=(
                            f"Model cited document_id '{ref.document_id}' which is not present "
                            "in the supplied verified records."
                        ),
                    )
                )
                continue

            if ref.document_id and ref.document_id in known_pages_by_doc:
                if ref.page_number not in known_pages_by_doc[ref.document_id]:
                    uncertainty_flags.append(
                        FieldUncertainty(
                            field_name=ref.field_name or "source_reference",
                            reason=(
                                f"Model cited page {ref.page_number} for document '{ref.document_id}', "
                                "which does not match known source pages."
                            ),
                        )
                    )
                    continue

            normalized_excerpt = " ".join(ref.excerpt.split()).lower()
            if normalized_excerpt not in normalized_corpus:
                uncertainty_flags.append(
                    FieldUncertainty(
                        field_name=ref.field_name or "source_reference",
                        reason="Model cited an excerpt not found in the supplied verified records.",
                    )
                )
                continue

            verified_refs.append(ref)
        return verified_refs

    def _validate_summary_payload(
        self,
        payload: dict[str, Any],
        validated_records: list[VerifiedRecordInput],
        raw_records: list[dict[str, Any]],
        language_code: str = "en",
        language_name: str = "English",
    ) -> dict[str, Any]:
        """Validate Gemini summary JSON and verify source references against supplied records."""
        try:
            parsed = _GeminiSummaryPayload.model_validate(payload)
        except ValidationError as e:
            raise ProviderResponseError(
                "Gemini response failed summary schema validation.",
                provider="gemini",
            ) from e

        valid_doc_ids = {r.document_id for r in validated_records if r.document_id}
        known_pages_by_doc = self._collect_known_pages_by_doc(raw_records)
        normalized_corpus = " ".join(
            json.dumps(raw_records, default=str, ensure_ascii=False).split()
        ).lower()

        uncertainty_flags = [
            FieldUncertainty(
                field_name=u.field_name.strip(),
                reason=u.reason.strip(),
                source_reference=self._to_source_reference(u.source_reference, u.field_name.strip()),
            )
            for u in parsed.uncertainty_flags
        ]

        verified_refs = self._verify_grounded_references(
            raw_refs=parsed.source_references,
            valid_doc_ids=valid_doc_ids,
            known_pages_by_doc=known_pages_by_doc,
            normalized_corpus=normalized_corpus,
            uncertainty_flags=uncertainty_flags,
        )

        result = SummaryResult(
            insufficient_data=False,
            patient_friendly_summary=parsed.patient_friendly_summary.strip(),
            doctor_ready_summary=parsed.doctor_ready_summary.strip(),
            key_findings=[f.strip() for f in parsed.key_findings if f and f.strip()],
            source_references=verified_refs,
            source_record_ids=sorted(valid_doc_ids),
            missing_information=[m.strip() for m in parsed.missing_information if m and m.strip()],
            conflicting_information=[c.strip() for c in parsed.conflicting_information if c and c.strip()],
            uncertainty_flags=uncertainty_flags,
            confidence=ConfidenceScore(
                score=parsed.confidence_score,
                source=self._model_source,
                category=parsed.confidence_category,
            ),
            provider_used="gemini",
            response_language=language_code,
            response_language_name=language_name,
            is_mock=False,
            is_clinically_verified=False,
        )
        return result.model_dump()

    async def answer_health_question(
        self,
        question: str,
        context_payload: dict[str, Any],
        response_language_code: str,
        source_language_code: Optional[str] = None,
        conversation_history: Optional[list[dict[str, str]]] = None,
    ) -> dict[str, Any]:
        """Answer a patient health question in the explicitly selected language using verified context."""
        resp_lang = validate_language_code(response_language_code)
        src_lang_label = (
            validate_language_code(source_language_code).name
            if source_language_code
            else "Auto/Unspecified"
        )

        serialized_context = json.dumps(context_payload, default=str, ensure_ascii=False)
        history_block = ""
        if conversation_history:
            history_lines = [
                f"- {t['role']}: {t['content']}"
                for t in conversation_history[-6:]
                if t.get("role") and t.get("content")
            ]
            if history_lines:
                history_block = "Recent Conversation:\n" + "\n".join(history_lines) + "\n\n"

        user_prompt = (
            f"Response Language (MANDATORY): {resp_lang.name} ({resp_lang.code})\n"
            f"Question Source Language: {src_lang_label}\n"
            f"Patient Question: {question}\n\n"
            f"{history_block}"
            f"Verified Patient Health Context:\n{serialized_context}"
        )

        raw_payload = await self._generate_json_with_retry(
            contents=user_prompt,
            system_instruction=_CONVERSATION_SYSTEM_INSTRUCTION,
            operation="conversational_qa",
        )

        try:
            parsed = _GeminiConversationPayload.model_validate(raw_payload)
        except ValidationError as e:
            raise ProviderResponseError(
                "Gemini response failed conversational schema validation.",
                provider="gemini",
            ) from e

        # Validate source references against supplied context
        normalized_corpus = " ".join(serialized_context.split()).lower()
        valid_doc_ids = set(context_payload.get("source_record_ids", []))
        known_pages_by_doc = self._collect_known_pages_by_doc(
            context_payload.get("verified_records", [])
        )
        uncertainty_flags = [
            FieldUncertainty(
                field_name=u.field_name.strip(),
                reason=u.reason.strip(),
                source_reference=self._to_source_reference(u.source_reference, u.field_name.strip()),
            )
            for u in parsed.uncertainty_flags
        ]
        verified_refs = self._verify_grounded_references(
            raw_refs=parsed.source_references,
            valid_doc_ids=valid_doc_ids,
            known_pages_by_doc=known_pages_by_doc,
            normalized_corpus=normalized_corpus,
            uncertainty_flags=uncertainty_flags,
        )

        documented_facts = [f.strip() for f in parsed.documented_facts if f and f.strip()]
        if documented_facts and not verified_refs and known_pages_by_doc:
            uncertainty_flags.append(
                FieldUncertainty(
                    field_name="source_references",
                    reason="Documented facts were returned without verifiable source references.",
                )
            )

        return {
            "answer": parsed.answer.strip(),
            "response_language": resp_lang.code,
            "response_language_name": resp_lang.name,
            "source_language": source_language_code,
            "documented_facts": documented_facts,
            "ai_observations": [o.strip() for o in parsed.ai_observations if o and o.strip()],
            "source_references": [r.model_dump() for r in verified_refs],
            "source_record_ids": sorted(valid_doc_ids),
            "missing_information": [m.strip() for m in parsed.missing_information if m and m.strip()],
            "conflicting_information": [c.strip() for c in parsed.conflicting_information if c and c.strip()],
            "uncertainty_flags": [u.model_dump() for u in uncertainty_flags],
            "insufficient_data": False,
            "is_clinical_diagnosis": False,
            "is_clinically_verified": False,
            "disclaimer": parsed.disclaimer.strip(),
            "confidence": ConfidenceScore(
                score=parsed.confidence_score,
                source=self._model_source,
                category=parsed.confidence_category,
            ).model_dump(),
            "provider_used": "gemini",
            "is_mock": False,
        }
