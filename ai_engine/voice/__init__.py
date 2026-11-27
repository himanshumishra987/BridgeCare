"""BridgeCare Voice (STT/TTS) integration interfaces and ElevenLabs adapters."""

from ai_engine.voice.audio_validator import (
    AudioValidationResult,
    detect_audio_mime_type,
    validate_audio_bytes,
)
from ai_engine.voice.config import VoiceConfig
from ai_engine.voice.elevenlabs_stt import (
    BRIDGECARE_TO_ELEVENLABS_STT_LANG,
    ElevenLabsSTTProvider,
)
from ai_engine.voice.elevenlabs_tts import ElevenLabsTTSProvider
from ai_engine.voice.interfaces import (
    SpeechToTextProvider,
    SpeechToTextResult,
    TextToSpeechProvider,
    TextToSpeechResult,
    UnconfiguredSpeechProvider,
    VoiceAssistantPipeline,
    VoiceCapabilityStatus,
    VoiceTurnResponse,
)

__all__ = [
    "AudioValidationResult",
    "BRIDGECARE_TO_ELEVENLABS_STT_LANG",
    "ElevenLabsSTTProvider",
    "ElevenLabsTTSProvider",
    "SpeechToTextProvider",
    "SpeechToTextResult",
    "TextToSpeechProvider",
    "TextToSpeechResult",
    "UnconfiguredSpeechProvider",
    "VoiceAssistantPipeline",
    "VoiceCapabilityStatus",
    "VoiceConfig",
    "VoiceTurnResponse",
    "detect_audio_mime_type",
    "validate_audio_bytes",
]
