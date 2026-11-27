# BridgeCare — ElevenLabs Voice Intelligence Integration Guide

## 1. Architecture & Provider Flow

```text
Patient Audio (bytes)
  │
  ▼ [1. Explicit Opt-In Consent Check: stt_consent_granted]
  ▼ [2. In-Memory Audio Validation: format, size, duration, silence]
ElevenLabsSTTProvider (Scribe v3 / Scribe v2 Medical)
  │
  ▼ [3. Transcript + Detected/Selected Language]
MultilingualHealthAssistant (Verified Records + Grounding + Provenance)
  │
  ▼ [4. Text Response (Always Preserved as Fallback)]
  ▼ [5. Explicit Opt-In Consent Check: tts_consent_granted & speak_response]
ElevenLabsTTSProvider (Eleven v4 / v4 Turbo + Per-Language Voice ID)
  │
  ▼
VoiceTurnResponse (assistant_response + stt_result + tts_result + voice_capability)
```

---

## 2. Installation & Configuration

Install the official Python SDK:
```powershell
.\.venv\Scripts\python.exe -m pip install elevenlabs
```

Environment settings (`ai_engine/voice/config.py`, **never commit `.env` or expose keys**):
- `ELEVENLABS_API_KEY`: ElevenLabs API key (loaded via `SecretStr`, never logged).
- `ELEVENLABS_STT_ENABLED`: `false` by default (explicit opt-in required).
- `ELEVENLABS_TTS_ENABLED`: `false` by default (explicit opt-in required).
- `ELEVENLABS_STT_MODEL`: `scribe_v3` (default) or `scribe_v2_medical` (clinical dictation).
- `ELEVENLABS_TTS_MODEL`: `eleven_v4` (default) or `eleven_v4_turbo` (low-latency interactive).
- `ELEVENLABS_TTS_OUTPUT_FORMAT`: `mp3_44100_128` (default).
- `ELEVENLABS_VOICE_ID_<CODE>` (e.g. `ELEVENLABS_VOICE_ID_EN`, `ELEVENLABS_VOICE_ID_HI`, `ELEVENLABS_VOICE_ID_KN`) or `ELEVENLABS_VOICE_IDS` JSON map.
- `ELEVENLABS_TIMEOUT_SECONDS`: `30.0` (default).
- `VOICE_MAX_AUDIO_SIZE_BYTES`: `26214400` (25 MB default).
- `VOICE_MAX_AUDIO_DURATION_SECONDS`: `300.0` (5 minutes default).

---

## 3. Model Evaluation

- **STT (`scribe_v3` vs `scribe_v2_medical`)**:
  - `scribe_v3` is the default batch model supporting 90+ languages (all 10 BridgeCare languages), mixed-language audio, and `numbers_format="digits"` (critical for preserving lab values and dosages).
  - `scribe_v2_medical` is selectable via `ELEVENLABS_STT_MODEL="scribe_v2_medical"` for specialized clinical/medical dictation.
- **TTS (`eleven_v4` vs `eleven_v4_turbo`)**:
  - `eleven_v4` is the default highest-quality model supporting 90+ languages with `stability` and `similarity_boost` voice settings.
  - `eleven_v4_turbo` provides ~100ms latency for real-time interactive agents over WebSocket.

---

## 4. Language Support & Voice Configuration

All 10 BridgeCare ISO 639-1 codes map to ElevenLabs Scribe ISO 639-3 codes (`en→eng`, `hi→hin`, `kn→kan`, `ta→tam`, `te→tel`, `bn→ben`, `mr→mar`, `gu→guj`, `ml→mal`, `or→ori`).

For TTS, **each language requires an explicitly configured `voice_id`** (`ELEVENLABS_VOICE_ID_<CODE>` or `ELEVENLABS_VOICE_IDS`). BridgeCare never silently substitutes an arbitrary voice or different language if a language's `voice_id` is unconfigured; instead it reports `VOICE_NOT_CONFIGURED` and retains text-based interaction.

---

## 5. Consent, Privacy & Regulatory Boundaries

- External STT and TTS are **opt-in** (`ELEVENLABS_STT_ENABLED`, `ELEVENLABS_TTS_ENABLED`, plus per-turn `stt_consent_granted` and `tts_consent_granted`).
- Health records are **never** transmitted to ElevenLabs; only the patient's spoken audio (STT) or the assistant's final response text (TTS) is sent.
- Voice recognition is never used for authentication.
- **Important Compliance Notice**: BridgeCare does not claim HIPAA compliance or production healthcare readiness for external speech processing. Appropriate contractual and privacy approvals—including a Business Associate Agreement (BAA) where applicable—must be executed before sending real patient PHI to ElevenLabs.

---

## 6. Safe Synthetic-Audio Test Procedure (After Approval)

1. Generate a synthetic WAV file locally using a non-PHI phrase (e.g., *"What is my hemoglobin level?"*).
2. Set `ELEVENLABS_STT_ENABLED=true`, `ELEVENLABS_TTS_ENABLED=true`, and configure `ELEVENLABS_VOICE_ID_EN=<your_premade_voice_id>` in `.env`.
3. Run a targeted Python check calling `VoiceAssistantPipeline.handle_audio_turn(...)` with `stt_consent_granted=True` and synthetic verified records, verifying the transcript, grounded assistant text, and synthesized audio bytes.
