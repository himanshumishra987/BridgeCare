from typing import Any

from ai_engine.languages import validate_language_code
from ai_engine.providers.base import AIProvider


class MockProvider(AIProvider):
    """Deterministic provider for development and testing."""

    async def classify_document(self, document_text: str) -> dict[str, Any]:
        text = document_text.lower()

        if any(word in text for word in ["hemoglobin", "platelets", "glucose", "cholesterol"]):
            document_type = "lab_report"
        elif any(word in text for word in ["tablet", "capsule", "dosage", "prescribed"]):
            document_type = "prescription"
        elif any(word in text for word in ["discharge", "admission", "hospital stay"]):
            document_type = "discharge_summary"
        elif any(word in text for word in ["insurance", "policy", "sum insured", "tpa", "premium"]):
            document_type = "insurance_doc"
        else:
            document_type = "other"

        return {
            "document_type": document_type,
            "raw_document_type": None,
            "confidence": {
                "score": None,
                "source": "mock",
                "category": "uncertain",
            },
            "uncertainty_flags": [],
            "provider_used": "mock",
            "is_mock": True,
        }

    async def extract_information(
        self,
        document_text: str,
        document_type: str,
    ) -> dict[str, Any]:
        return {
            "document_type": document_type,
            "document_date": None,
            "hospital_or_lab_name": None,
            "doctor_name": None,
            "patient_name": None,
            "biomarkers": [],
            "medications": [],
            "clinical_events": [],
            "missing_fields": ["Extraction not implemented in mock provider"],
            "uncertainty_flags": [],
            "overall_confidence": {
                "score": None,
                "source": "mock",
                "category": "uncertain",
            },
        }

    async def generate_summary(
        self,
        verified_records: list[dict[str, Any]],
        language_code: str = "en",
    ) -> dict[str, Any]:
        lang_info = validate_language_code(language_code)
        return {
            "summary": "Mock summary only. No clinical interpretation performed.",
            "source": "mock",
            "is_mock": True,
            "response_language": lang_info.code,
            "response_language_name": lang_info.name,
            "source_records": [],
        }
