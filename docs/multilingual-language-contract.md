# BridgeCare — Global Language Preference & Multilingual AI Integration Contract

**Audience:** Shreyash (Backend) & Ujjwal (Frontend)
**Scope:** Integration contract between Frontend Global Language Selector, Backend User Profile Persistence, and the AI Engine (`ai_engine`).

---

## 1. Supported Language Codes (10 Languages)

All three layers must use canonical ISO 639-1 codes defined in `ai_engine/languages.py`:

| Code | Language Name | Native Name | Tesseract OCR Code |
| :--- | :--- | :--- | :--- |
| `en` | English | English | `eng` |
| `hi` | Hindi | हिन्दी | `hin` |
| `kn` | Kannada | ಕನ್ನಡ | `kan` |
| `ta` | Tamil | தமிழ் | `tam` |
| `te` | Telugu | తెలుగు | `tel` |
| `bn` | Bengali | বাংলা | `ben` |
| `mr` | Marathi | मराठी | `mar` |
| `gu` | Gujarati | ગુજરાતી | `guj` |
| `ml` | Malayalam | മലയാളം | `mal` |
| `or` | Odia | ଓଡ଼ିଆ | `ori` |

Unsupported codes raise `UnsupportedLanguageError` (`error_type="UNSUPPORTED_LANGUAGE"`), which the backend should map to HTTP `422 Unprocessable Entity` or `400 Bad Request`.

---

## 2. Standard Language Contract (`LanguagePreference`)

Defined in `ai_engine.languages.LanguagePreference`:

```json
{
  "language_code": "kn",
  "language_name": "Kannada",
  "source_language": "en",
  "response_language": "kn"
}
```

- `language_code` (required): User's globally selected language code.
- `language_name` (optional on input, auto-populated on validation): Canonical English name.
- `source_language` (optional): Language of the user's question or uploaded document, if known.
- `response_language` (optional on input, defaults to `language_code`): Explicit target language for AI output.

**Precedence Rule:** `response_language` (derived from the user's selected `language_code`) **always takes precedence** over `source_language` or the detected language of the question/document.

---

## 3. Frontend & Backend Integration Flow

1. **Frontend (Ujjwal)**:
   - Renders a global language selector offering the 10 supported languages.
   - On change, calls the backend user-profile endpoint (e.g., `PATCH /api/v1/users/me/preferences` with `{"preferred_language": "kn"}`) and updates client state.
   - Sends `language_code` (or full `language` object) in AI chat and summary requests, and reads `response_language` / `response_language_name` from AI responses to render localized UI labels and RTL/script fonts cleanly.
2. **Backend (Shreyash)**:
   - Persists `preferred_language` (default `"en"`) on the user profile in the database so preference survives session reloads.
   - When calling AI endpoints (`MultilingualHealthAssistant.answer_question` or `GeminiProvider.generate_summary`), supplies the user's saved `preferred_language` (or explicit request override) in `LanguagePreference` / `language_code`.
   - Enforces authentication/authorization and passes **only** `verified` or `edited_verified` records to the assistant and summary services.

---

## 4. AI Engine Endpoints & Response Metadata

- **Conversational Q&A (`MultilingualHealthAssistant.answer_question`)**:
  - Input: `AssistantChatRequest` (`question`, `language: LanguagePreference`, `verified_records`, optional `conversation_history`).
  - Output: `AssistantChatResponse` containing `answer`, `response_language`, `response_language_name`, `documented_facts`, `ai_observations`, `source_references`, `missing_information`, `conflicting_information`, `is_clinical_diagnosis=False`, `is_clinically_verified=False`, and `disclaimer`.
- **Summaries (`GeminiProvider.generate_summary(verified_records, language_code="kn")`)**:
  - Output: `SummaryResult` containing `response_language`, `response_language_name`, `patient_friendly_summary`, and `doctor_ready_summary` in the selected language while preserving exact numbers, units, dates, medicine names, and verbatim `source_references`.
- **OCR Language Check (`check_ocr_language_support(language_code)`)**:
  - Reports whether the host Tesseract installation has the required `tessdata` pack (e.g., `kan.traineddata`), surfacing explicit limitations if unavailable.
- **Voice Interface (`VoiceAssistantPipeline.get_capability_status(language_code)`)**:
  - Exposes `stt_supported`, `tts_supported`, and `fallback_to_text=True` so the frontend gracefully retains text interaction when speech providers are not configured.
