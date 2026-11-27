"""Canonical language registry and validation for BridgeCare multilingual AI."""

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SupportedLanguage(str, Enum):
    """The 10 supported languages for BridgeCare's multilingual AI capabilities."""

    EN = "en"
    HI = "hi"
    KN = "kn"
    TA = "ta"
    TE = "te"
    BN = "bn"
    MR = "mr"
    GU = "gu"
    ML = "ml"
    OR = "or"


@dataclass(frozen=True)
class LanguageInfo:
    """Metadata for a supported language."""

    code: str
    name: str
    native_name: str
    tesseract_code: str


LANGUAGE_REGISTRY: dict[str, LanguageInfo] = {
    "en": LanguageInfo(code="en", name="English", native_name="English", tesseract_code="eng"),
    "hi": LanguageInfo(code="hi", name="Hindi", native_name="हिन्दी", tesseract_code="hin"),
    "kn": LanguageInfo(code="kn", name="Kannada", native_name="ಕನ್ನಡ", tesseract_code="kan"),
    "ta": LanguageInfo(code="ta", name="Tamil", native_name="தமிழ்", tesseract_code="tam"),
    "te": LanguageInfo(code="te", name="Telugu", native_name="తెలుగు", tesseract_code="tel"),
    "bn": LanguageInfo(code="bn", name="Bengali", native_name="বাংলা", tesseract_code="ben"),
    "mr": LanguageInfo(code="mr", name="Marathi", native_name="मराठी", tesseract_code="mar"),
    "gu": LanguageInfo(code="gu", name="Gujarati", native_name="ગુજરાતી", tesseract_code="guj"),
    "ml": LanguageInfo(code="ml", name="Malayalam", native_name="മലയാളം", tesseract_code="mal"),
    "or": LanguageInfo(code="or", name="Odia", native_name="ଓଡ଼ିଆ", tesseract_code="ori"),
}


class UnsupportedLanguageError(ValueError):
    """Raised when an unsupported language code is requested."""

    def __init__(self, language_code: str):
        supported = ", ".join(sorted(LANGUAGE_REGISTRY.keys()))
        self.error_type = "UNSUPPORTED_LANGUAGE"
        self.message = (
            f"Unsupported language code '{language_code}'. "
            f"Supported language codes are: {supported}."
        )
        self.provider = "language_registry"
        self.retryable = False
        super().__init__(self.message)


def validate_language_code(code: str) -> LanguageInfo:
    """Validate and resolve a language code against the 10 supported BridgeCare languages."""
    if not isinstance(code, str) or not code.strip():
        raise UnsupportedLanguageError(str(code))
    normalized = code.strip().lower()
    if normalized not in LANGUAGE_REGISTRY:
        raise UnsupportedLanguageError(code)
    return LANGUAGE_REGISTRY[normalized]


class LanguagePreference(BaseModel):
    """Global language preference API contract for frontend, backend, and AI engine."""

    model_config = ConfigDict(extra="forbid")

    language_code: str
    language_name: Optional[str] = None
    source_language: Optional[str] = None
    response_language: Optional[str] = None

    @model_validator(mode="after")
    def validate_and_normalize(self) -> "LanguagePreference":
        info = validate_language_code(self.language_code)
        self.language_code = info.code
        self.language_name = info.name

        if self.source_language is not None:
            src_info = validate_language_code(self.source_language)
            self.source_language = src_info.code

        if self.response_language is not None:
            resp_info = validate_language_code(self.response_language)
            self.response_language = resp_info.code
        else:
            self.response_language = info.code

        return self


class LanguageDetectionResult(BaseModel):
    """Structured result of deterministic script-based source language detection."""

    model_config = ConfigDict(extra="forbid")

    detected_language: Optional[str] = None
    candidate_languages: list[str] = Field(default_factory=list)
    detected_scripts: list[str] = Field(default_factory=list)
    is_mixed_language: bool = False
    uncertain: bool = False
    reason: Optional[str] = None


def _classify_char_script(ch: str) -> Optional[str]:
    if not ch.isalpha():
        return None
    cp = ord(ch)
    if (0x0041 <= cp <= 0x005A) or (0x0061 <= cp <= 0x007A):
        return "latin"
    if 0x0900 <= cp <= 0x097F:
        return "devanagari"
    if 0x0C80 <= cp <= 0x0CFF:
        return "kannada"
    if 0x0B80 <= cp <= 0x0BFF:
        return "tamil"
    if 0x0C00 <= cp <= 0x0C7F:
        return "telugu"
    if 0x0980 <= cp <= 0x09FF:
        return "bengali"
    if 0x0A80 <= cp <= 0x0AFF:
        return "gujarati"
    if 0x0D00 <= cp <= 0x0D7F:
        return "malayalam"
    if 0x0B00 <= cp <= 0x0B7F:
        return "odia"
    return "unsupported_other"


_SCRIPT_TO_CODE: dict[str, str] = {
    "latin": "en",
    "kannada": "kn",
    "tamil": "ta",
    "telugu": "te",
    "bengali": "bn",
    "gujarati": "gu",
    "malayalam": "ml",
    "odia": "or",
}


def detect_source_language(text: str) -> LanguageDetectionResult:
    """Detect source language deterministically from Unicode scripts without guessing.

    Never silently guesses between Hindi (hi) and Marathi (mr) for Devanagari text,
    and flags mixed-language or unsupported-script inputs as uncertain.
    """
    if not text or not text.strip():
        return LanguageDetectionResult(
            detected_language=None,
            uncertain=True,
            reason="Empty text cannot be used for language detection.",
        )

    counts: Counter[str] = Counter()
    for ch in text:
        script = _classify_char_script(ch)
        if script is not None:
            counts[script] += 1

    if not counts:
        return LanguageDetectionResult(
            detected_language=None,
            uncertain=True,
            reason="No alphabetic script characters found for language detection.",
        )

    scripts = sorted(counts.keys())
    total_chars = sum(counts.values())

    if "unsupported_other" in counts:
        return LanguageDetectionResult(
            detected_language=None,
            candidate_languages=[],
            detected_scripts=scripts,
            is_mixed_language=len(scripts) > 1,
            uncertain=True,
            reason="Detected script outside the 10 supported BridgeCare languages.",
        )

    if len(scripts) > 1:
        candidates: list[str] = []
        for sc in scripts:
            if sc == "devanagari":
                candidates.extend(["hi", "mr"])
            elif sc in _SCRIPT_TO_CODE:
                candidates.append(_SCRIPT_TO_CODE[sc])
        dominant_script, dominant_count = counts.most_common(1)[0]
        if dominant_script != "devanagari" and (dominant_count / total_chars) >= 0.65:
            return LanguageDetectionResult(
                detected_language=_SCRIPT_TO_CODE[dominant_script],
                candidate_languages=candidates,
                detected_scripts=scripts,
                is_mixed_language=True,
                uncertain=False,
                reason="Mixed-script text detected; dominant script identified.",
            )
        return LanguageDetectionResult(
            detected_language=None,
            candidate_languages=candidates,
            detected_scripts=scripts,
            is_mixed_language=True,
            uncertain=True,
            reason="Mixed-language text detected without a single dominant unambiguous script.",
        )

    only_script = scripts[0]
    if only_script == "devanagari":
        return LanguageDetectionResult(
            detected_language=None,
            candidate_languages=["hi", "mr"],
            detected_scripts=scripts,
            is_mixed_language=False,
            uncertain=True,
            reason="Devanagari script is shared by Hindi (hi) and Marathi (mr); explicit language selection recommended.",
        )

    code = _SCRIPT_TO_CODE[only_script]
    return LanguageDetectionResult(
        detected_language=code,
        candidate_languages=[code],
        detected_scripts=scripts,
        is_mixed_language=False,
        uncertain=False,
    )
