"""Automated tests for Milestone 2: Gemini-powered document classification."""

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from google.genai import errors as genai_errors
from pydantic import ValidationError
import pytest

from ai_engine.providers import (
    AIProviderConfig,
    GeminiProvider,
    MockProvider,
    ProviderAPIError,
    ProviderConfigurationError,
    ProviderResponseError,
    ProviderTimeoutError,
    get_ai_provider,
)
from ai_engine.schemas.classification import ClassificationResult, DocumentType
from ai_engine.schemas.common import ConfidenceCategory


def _make_mock_client(response_text: str | None = None, side_effect=None) -> MagicMock:
    """Create a mock google-genai Client with an async aio.models.generate_content method."""
    client = MagicMock()
    if side_effect is not None:
        client.aio.models.generate_content = AsyncMock(side_effect=side_effect)
    else:
        client.aio.models.generate_content = AsyncMock(
            return_value=SimpleNamespace(text=response_text)
        )
    return client


def _make_gemini_config(**overrides) -> AIProviderConfig:
    defaults = {
        "bridgecare_ai_provider": "gemini",
        "gemini_api_key": "synthetic-test-api-key-12345",
        "gemini_model": "gemini-2.5-flash",
        "gemini_timeout_seconds": 5.0,
        "gemini_max_retries": 2,
        "gemini_retry_base_delay_seconds": 0.0,
    }
    defaults.update(overrides)
    return AIProviderConfig(**defaults)


# =============================================================================
# 1. All 7 Supported Categories + Consultation Summary -> clinical_note
# =============================================================================


@pytest.mark.parametrize(
    "expected_category,sample_text",
    [
        (
            DocumentType.LAB_REPORT,
            "Synthetic Lab Report: Hemoglobin 14.2 g/dL, WBC 6,500 /uL, Platelets 240,000 /uL.",
        ),
        (
            DocumentType.PRESCRIPTION,
            "Rx: Tab Metformin 500 mg, 1 tablet twice daily after meals for 30 days.",
        ),
        (
            DocumentType.DISCHARGE_SUMMARY,
            "Hospital Discharge Summary: Admitted 2026-01-10, Discharged 2026-01-14. Condition stable.",
        ),
        (
            DocumentType.CLINICAL_NOTE,
            "Outpatient Consultation Summary: Patient presented with mild seasonal cough. Follow up in 1 week.",
        ),
        (
            DocumentType.AYUSH_RECORD,
            "Ayurvedic Consultation Record: Triphala Churna 3g at bedtime with warm water for 14 days.",
        ),
        (
            DocumentType.INSURANCE_DOC,
            "Health Insurance Policy Pre-Authorization Form: Policy #SYN-9988, Claim Reference 4421.",
        ),
        (
            DocumentType.OTHER,
            "General hospital parking receipt and administrative visitor pass for building B.",
        ),
    ],
)
@pytest.mark.asyncio
async def test_all_seven_supported_categories(expected_category: DocumentType, sample_text: str):
    """Test classification across all seven canonical BridgeCare document categories."""
    payload = json.dumps(
        {
            "document_type": expected_category.value,
            "raw_document_type": expected_category.value,
            "confidence_score": 0.94,
            "confidence_category": "high",
            "uncertainty_reasons": [],
        }
    )
    mock_client = _make_mock_client(response_text=payload)
    cfg = _make_gemini_config()
    provider = GeminiProvider(config=cfg, client=mock_client)

    raw_result = await provider.classify_document(sample_text)
    validated = ClassificationResult.model_validate(raw_result)

    assert validated.document_type == expected_category
    assert validated.provider_used == "gemini"
    assert validated.is_mock is False
    assert validated.confidence.score == pytest.approx(0.94)
    assert validated.confidence.category == ConfidenceCategory.HIGH
    assert validated.confidence.source == "gemini:gemini-2.5-flash"

    # Ensure configured model was passed to SDK (not hardcoded)
    call_kwargs = mock_client.aio.models.generate_content.call_args.kwargs
    assert call_kwargs["model"] == "gemini-2.5-flash"


@pytest.mark.asyncio
async def test_configured_model_is_used():
    """Verify that GEMINI_MODEL from config is passed to the SDK instead of a hardcoded model."""
    payload = json.dumps(
        {
            "document_type": "clinical_note",
            "raw_document_type": "consultation_summary",
            "confidence_score": 0.9,
            "confidence_category": "high",
            "uncertainty_reasons": [],
        }
    )
    mock_client = _make_mock_client(response_text=payload)
    cfg = _make_gemini_config(gemini_model="gemini-2.5-pro")
    provider = GeminiProvider(config=cfg, client=mock_client)

    result = await provider.classify_document(
        "Consultation summary: Routine annual wellness visit, vitals within normal limits."
    )
    validated = ClassificationResult.model_validate(result)
    assert validated.document_type == DocumentType.CLINICAL_NOTE
    assert validated.confidence.source == "gemini:gemini-2.5-pro"
    assert mock_client.aio.models.generate_content.call_args.kwargs["model"] == "gemini-2.5-pro"


# =============================================================================
# 2. Ambiguous Documents & Insufficient Text
# =============================================================================


@pytest.mark.asyncio
async def test_ambiguous_document_preserves_uncertainty():
    """Test that ambiguous documents preserve uncertainty flags and low/uncertain confidence."""
    payload = json.dumps(
        {
            "document_type": "other",
            "raw_document_type": "partial_fragment",
            "confidence_score": 0.35,
            "confidence_category": "uncertain",
            "uncertainty_reasons": [
                "Document contains mixed billing codes and partial clinical terms without clear context."
            ],
        }
    )
    mock_client = _make_mock_client(response_text=payload)
    provider = GeminiProvider(config=_make_gemini_config(), client=mock_client)

    result = await provider.classify_document(
        "Ref: 4021 - Follow-up item pending balance and observation note."
    )
    validated = ClassificationResult.model_validate(result)

    assert validated.document_type == DocumentType.OTHER
    assert validated.confidence.category == ConfidenceCategory.UNCERTAIN
    assert validated.confidence.score == pytest.approx(0.35)
    assert len(validated.uncertainty_flags) == 1
    assert "mixed billing codes" in validated.uncertainty_flags[0].reason


@pytest.mark.asyncio
async def test_insufficient_document_text_returns_uncertain_without_hallucinating():
    """Test that insufficient text is flagged as uncertain without inventing a confident category."""
    mock_client = _make_mock_client(response_text="{}")
    provider = GeminiProvider(config=_make_gemini_config(), client=mock_client)

    # Empty string raises Pydantic ValidationError
    with pytest.raises(ValidationError):
        await provider.classify_document("")

    # Very short / non-meaningful text returns uncertain 'other' without calling API
    result = await provider.classify_document("... N/A ---")
    validated = ClassificationResult.model_validate(result)

    assert validated.document_type == DocumentType.OTHER
    assert validated.confidence.category == ConfidenceCategory.UNCERTAIN
    assert validated.confidence.score is None
    assert len(validated.uncertainty_flags) == 1
    assert "Insufficient document text" in validated.uncertainty_flags[0].reason
    mock_client.aio.models.generate_content.assert_not_called()


# =============================================================================
# 3. Malformed JSON, Missing Fields, Unexpected Categories
# =============================================================================


@pytest.mark.asyncio
async def test_malformed_json_raises_response_error():
    """Test that malformed JSON raises ProviderResponseError and never falls back to mock."""
    mock_client = _make_mock_client(response_text="{not valid json:::")
    provider = GeminiProvider(config=_make_gemini_config(), client=mock_client)

    with pytest.raises(ProviderResponseError) as exc_info:
        await provider.classify_document("Synthetic lab report with Hemoglobin 13.0 g/dL.")

    assert exc_info.value.error_type == "PROVIDER_RESPONSE_ERROR"
    assert exc_info.value.provider == "gemini"


@pytest.mark.asyncio
async def test_missing_required_field_raises_response_error():
    """Test that missing document_type in JSON raises ProviderResponseError."""
    payload = json.dumps({"confidence_score": 0.9, "confidence_category": "high"})
    mock_client = _make_mock_client(response_text=payload)
    provider = GeminiProvider(config=_make_gemini_config(), client=mock_client)

    with pytest.raises(ProviderResponseError):
        await provider.classify_document("Synthetic prescription for Paracetamol 500mg.")


@pytest.mark.asyncio
async def test_unexpected_category_value_raises_response_error():
    """Test that unexpected/non-canonical category values fail Pydantic validation."""
    payload = json.dumps(
        {
            "document_type": "radiology_dicom_unknown",
            "confidence_score": 0.88,
            "confidence_category": "high",
        }
    )
    mock_client = _make_mock_client(response_text=payload)
    provider = GeminiProvider(config=_make_gemini_config(), client=mock_client)

    with pytest.raises(ProviderResponseError):
        await provider.classify_document("Synthetic imaging report text for chest X-ray.")


# =============================================================================
# 4. Timeouts, Rate Limits, API Failures, and Retry Limits
# =============================================================================


@pytest.mark.asyncio
async def test_gemini_api_timeout_retries_and_raises():
    """Test bounded timeout and retry exhaustion raises ProviderTimeoutError."""
    async def slow_call(**kwargs):
        await asyncio.sleep(0.2)
        return SimpleNamespace(text="{}")

    mock_client = _make_mock_client(side_effect=slow_call)
    cfg = _make_gemini_config(
        gemini_timeout_seconds=0.02,
        gemini_max_retries=2,
        gemini_retry_base_delay_seconds=0.0,
    )
    provider = GeminiProvider(config=cfg, client=mock_client)

    with pytest.raises(ProviderTimeoutError) as exc_info:
        await provider.classify_document("Synthetic discharge summary text for timeout test.")

    assert exc_info.value.error_type == "PROVIDER_TIMEOUT"
    # 1 initial attempt + 2 retries = 3 total attempts
    assert mock_client.aio.models.generate_content.call_count == 3


@pytest.mark.asyncio
async def test_rate_limit_retries_and_recovers():
    """Test 429 rate limit retries up to configured limit and succeeds on recovery."""
    rate_limit_err = genai_errors.APIError(429, {"error": {"message": "Rate limit exceeded"}})
    success_payload = json.dumps(
        {
            "document_type": "prescription",
            "confidence_score": 0.91,
            "confidence_category": "high",
            "uncertainty_reasons": [],
        }
    )
    mock_client = _make_mock_client(
        side_effect=[rate_limit_err, SimpleNamespace(text=success_payload)]
    )
    cfg = _make_gemini_config(gemini_max_retries=2, gemini_retry_base_delay_seconds=0.0)
    provider = GeminiProvider(config=cfg, client=mock_client)

    result = await provider.classify_document("Rx: Amoxicillin 500mg capsule three times daily.")
    validated = ClassificationResult.model_validate(result)

    assert validated.document_type == DocumentType.PRESCRIPTION
    assert mock_client.aio.models.generate_content.call_count == 2


@pytest.mark.asyncio
async def test_rate_limit_exhausts_retries_and_raises_without_mock_fallback():
    """Test persistent 429 rate limit raises ProviderAPIError and never falls back to mock."""
    rate_limit_err = genai_errors.APIError(429, {"error": {"message": "Quota exceeded"}})
    mock_client = _make_mock_client(side_effect=rate_limit_err)
    cfg = _make_gemini_config(gemini_max_retries=2, gemini_retry_base_delay_seconds=0.0)
    provider = GeminiProvider(config=cfg, client=mock_client)

    with pytest.raises(ProviderAPIError) as exc_info:
        await provider.classify_document("Synthetic lab report: Glucose 95 mg/dL.")

    assert exc_info.value.error_type == "PROVIDER_RATE_LIMIT"
    assert exc_info.value.status_code == 429
    assert mock_client.aio.models.generate_content.call_count == 3


@pytest.mark.asyncio
async def test_non_retryable_api_error_fails_immediately_and_hides_key():
    """Test 401/403 API errors fail immediately without retries and never expose API key."""
    secret_key = "SUPER-SECRET-DO-NOT-LEAK-KEY"
    auth_err = genai_errors.APIError(401, {"error": {"message": "Invalid API key"}})
    mock_client = _make_mock_client(side_effect=auth_err)
    cfg = _make_gemini_config(
        gemini_api_key=secret_key,
        gemini_max_retries=3,
        gemini_retry_base_delay_seconds=0.0,
    )
    provider = GeminiProvider(config=cfg, client=mock_client)

    with pytest.raises(ProviderAPIError) as exc_info:
        await provider.classify_document("Synthetic clinical note: Patient is doing well.")

    assert exc_info.value.error_type == "PROVIDER_API_ERROR"
    assert exc_info.value.status_code == 401
    assert secret_key not in str(exc_info.value)
    assert secret_key not in repr(cfg)
    assert mock_client.aio.models.generate_content.call_count == 1


# =============================================================================
# 5. Explicit Provider Selection & Missing Credentials
# =============================================================================


def test_explicit_mock_provider_selection(monkeypatch):
    """Test BRIDGECARE_AI_PROVIDER=mock returns MockProvider."""
    monkeypatch.setenv("BRIDGECARE_AI_PROVIDER", "mock")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    provider = get_ai_provider(AIProviderConfig(_env_file=None))
    assert isinstance(provider, MockProvider)


def test_explicit_gemini_provider_selection(monkeypatch):
    """Test BRIDGECARE_AI_PROVIDER=gemini with credentials returns GeminiProvider."""
    monkeypatch.setenv("BRIDGECARE_AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key-for-selection-test")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")

    provider = get_ai_provider(AIProviderConfig(_env_file=None))
    assert isinstance(provider, GeminiProvider)
    assert provider.config.gemini_model == "gemini-2.5-flash"


def test_missing_gemini_credentials_raises_configuration_error(monkeypatch):
    """Test selecting gemini without GEMINI_API_KEY raises ProviderConfigurationError."""
    monkeypatch.setenv("BRIDGECARE_AI_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(ProviderConfigurationError) as exc_info:
        get_ai_provider(AIProviderConfig(_env_file=None))

    assert "GEMINI_API_KEY is required" in exc_info.value.message


def test_unsupported_provider_selection_raises_configuration_error(monkeypatch):
    """Test unsupported BRIDGECARE_AI_PROVIDER raises ProviderConfigurationError."""
    monkeypatch.setenv("BRIDGECARE_AI_PROVIDER", "unsupported_xyz")

    with pytest.raises(ProviderConfigurationError):
        get_ai_provider(AIProviderConfig(_env_file=None))


# =============================================================================
# 6. Optional Live Integration Test (runs only when GEMINI_API_KEY is set)
# =============================================================================


def _has_live_gemini_key() -> bool:
    cfg = AIProviderConfig()
    key = cfg.gemini_api_key.get_secret_value().strip() if cfg.gemini_api_key else ""
    return bool(key) and not key.startswith("synthetic-")


@pytest.mark.skipif(
    not _has_live_gemini_key(),
    reason="Live Gemini API key not configured; skipping live integration test.",
)
@pytest.mark.asyncio
async def test_live_gemini_classification_synthetic_document():
    """Optional live integration test against Gemini API using synthetic document text."""
    cfg = AIProviderConfig(bridgecare_ai_provider="gemini")
    provider = get_ai_provider(cfg)
    assert isinstance(provider, GeminiProvider)

    synthetic_lab_text = (
        "SYNTHETIC DIAGNOSTIC LABORATORY REPORT\n"
        "Test Name: Complete Blood Count (CBC)\n"
        "Hemoglobin: 13.8 g/dL (Reference: 12.0 - 16.0 g/dL)\n"
        "Total Leukocyte Count: 7,200 /uL (Reference: 4,000 - 11,000 /uL)\n"
        "Platelet Count: 235,000 /uL (Reference: 150,000 - 450,000 /uL)\n"
    )
    result = await provider.classify_document(synthetic_lab_text)
    validated = ClassificationResult.model_validate(result)

    assert validated.document_type == DocumentType.LAB_REPORT
    assert validated.provider_used == "gemini"
    assert validated.is_mock is False
