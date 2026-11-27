"""In-memory audio format, size, duration, and silence validation for STT."""

from dataclasses import dataclass
import io
import struct
from typing import Optional
import wave

from ai_engine.voice.config import VoiceConfig

SUPPORTED_AUDIO_MIME_TYPES = frozenset(
    {
        "audio/wav",
        "audio/x-wav",
        "audio/mpeg",
        "audio/mp3",
        "audio/ogg",
        "audio/opus",
        "audio/flac",
        "audio/mp4",
        "audio/m4a",
        "audio/webm",
    }
)

_MIME_ALIASES: dict[str, str] = {
    "audio/mp3": "audio/mpeg",
    "audio/x-wav": "audio/wav",
    "audio/m4a": "audio/mp4",
    "audio/opus": "audio/ogg",
}

_MIME_TO_EXT = {
    "audio/wav": "wav",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "audio/flac": "flac",
    "audio/mp4": "m4a",
    "audio/webm": "webm",
}


@dataclass(frozen=True)
class AudioValidationResult:
    """Result of in-memory audio validation."""

    is_valid: bool
    detected_mime_type: Optional[str] = None
    filename: str = "audio.wav"
    duration_seconds: Optional[float] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


def detect_audio_mime_type(audio_bytes: bytes) -> Optional[str]:
    """Detect audio format from magic bytes without trusting file extensions."""
    if len(audio_bytes) >= 12 and audio_bytes[:4] == b"RIFF" and audio_bytes[8:12] == b"WAVE":
        return "audio/wav"
    if audio_bytes.startswith(b"ID3") or (
        len(audio_bytes) >= 2 and audio_bytes[0] == 0xFF and (audio_bytes[1] & 0xE0) == 0xE0
    ):
        return "audio/mpeg"
    if audio_bytes.startswith(b"OggS"):
        return "audio/ogg"
    if audio_bytes.startswith(b"fLaC"):
        return "audio/flac"
    if len(audio_bytes) >= 12 and audio_bytes[4:8] == b"ftyp":
        return "audio/mp4"
    if audio_bytes.startswith(b"\x1a\x45\xdf\xa3"):
        return "audio/webm"
    return None


def _inspect_wav_duration_and_silence(audio_bytes: bytes) -> tuple[Optional[float], bool, Optional[str]]:
    """Inspect a WAV stream for valid headers, duration, and complete silence across bit depths.

    Inspects all frames in the audio stream. Audio is considered silent ONLY if every sample
    is zero/silence. Audio with leading or trailing silence followed by speech is not rejected.
    """
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            sampwidth = wf.getsampwidth()
            if rate <= 0:
                return None, False, "Malformed WAV header: invalid sample rate."
            duration = frames / float(rate)
            if frames == 0:
                return 0.0, True, "WAV audio contains zero frames."

            raw = wf.readframes(frames)
            if not raw:
                return duration, True, "WAV audio contains zero data frames."

            is_silent = False
            if sampwidth == 2:  # 16-bit signed PCM
                sample_count = len(raw) // 2
                if sample_count > 0:
                    samples = struct.unpack(f"<{sample_count}h", raw[: sample_count * 2])
                    if all(s == 0 for s in samples):
                        is_silent = True
            elif sampwidth == 1:  # 8-bit unsigned PCM (128 or 0 is silence)
                if all(b == 128 or b == 0 for b in raw):
                    is_silent = True
            elif sampwidth == 3:  # 24-bit PCM
                if all(b == 0 for b in raw):
                    is_silent = True
            elif sampwidth == 4:  # 32-bit signed PCM
                sample_count = len(raw) // 4
                if sample_count > 0:
                    samples = struct.unpack(f"<{sample_count}i", raw[: sample_count * 4])
                    if all(s == 0 for s in samples):
                        is_silent = True
            else:
                if all(b == 0 for b in raw):
                    is_silent = True

            if is_silent:
                return duration, True, "Audio appears to be completely silent."

            return duration, False, None
    except wave.Error:
        return None, False, "Malformed or corrupt WAV audio stream."


def validate_audio_bytes(
    audio_bytes: bytes,
    config: Optional[VoiceConfig] = None,
    declared_mime_type: Optional[str] = None,
    duration_seconds: Optional[float] = None,
) -> AudioValidationResult:
    """Validate audio bytes in-memory before sending to an external STT provider."""
    cfg = config or VoiceConfig()

    if not audio_bytes:
        return AudioValidationResult(
            is_valid=False,
            error_code="EMPTY_AUDIO",
            error_message="Audio input is empty (0 bytes).",
        )

    if len(audio_bytes) > cfg.max_audio_size_bytes:
        return AudioValidationResult(
            is_valid=False,
            error_code="AUDIO_TOO_LARGE",
            error_message=(
                f"Audio size ({len(audio_bytes)} bytes) exceeds maximum allowed limit "
                f"of {cfg.max_audio_size_bytes} bytes."
            ),
        )

    if declared_mime_type and declared_mime_type.strip().lower() not in SUPPORTED_AUDIO_MIME_TYPES:
        return AudioValidationResult(
            is_valid=False,
            error_code="UNSUPPORTED_AUDIO_MIME",
            error_message=f"Unsupported declared audio MIME type '{declared_mime_type}'.",
        )

    detected_mime = detect_audio_mime_type(audio_bytes)
    if detected_mime is None:
        return AudioValidationResult(
            is_valid=False,
            error_code="INVALID_AUDIO_SIGNATURE",
            error_message="Unrecognized or malformed audio format signature.",
        )

    # Check for declared vs detected MIME mismatch (using canonical MIME aliases)
    if declared_mime_type:
        decl_canonical = _MIME_ALIASES.get(declared_mime_type.strip().lower(), declared_mime_type.strip().lower())
        det_canonical = _MIME_ALIASES.get(detected_mime, detected_mime)
        if decl_canonical != det_canonical:
            return AudioValidationResult(
                is_valid=False,
                detected_mime_type=detected_mime,
                error_code="MIME_MISMATCH",
                error_message=(
                    f"Declared MIME type '{declared_mime_type}' does not match detected "
                    f"format '{detected_mime}'."
                ),
            )

    measured_duration = duration_seconds
    if detected_mime == "audio/wav":
        wav_duration, is_silent, wav_err = _inspect_wav_duration_and_silence(audio_bytes)
        if wav_err:
            return AudioValidationResult(
                is_valid=False,
                detected_mime_type=detected_mime,
                duration_seconds=wav_duration,
                error_code="SILENT_OR_MALFORMED_AUDIO" if is_silent else "MALFORMED_AUDIO",
                error_message=wav_err,
            )
        measured_duration = wav_duration
    else:
        # Non-WAV formats: compressed audio cannot reliably yield duration without full decoding
        if measured_duration is None:
            return AudioValidationResult(
                is_valid=False,
                detected_mime_type=detected_mime,
                error_code="DURATION_UNDETERMINED",
                error_message=(
                    f"Duration cannot be safely determined from {detected_mime} container alone; "
                    "provide trusted duration_seconds metadata."
                ),
            )

    if measured_duration is not None:
        if measured_duration <= 0.0:
            return AudioValidationResult(
                is_valid=False,
                detected_mime_type=detected_mime,
                duration_seconds=measured_duration,
                error_code="INVALID_AUDIO_DURATION",
                error_message="Audio duration must be greater than 0 seconds.",
            )
        if measured_duration > cfg.max_audio_duration_seconds:
            return AudioValidationResult(
                is_valid=False,
                detected_mime_type=detected_mime,
                duration_seconds=measured_duration,
                error_code="AUDIO_DURATION_EXCEEDED",
                error_message=(
                    f"Audio duration ({measured_duration:.1f}s) exceeds maximum allowed "
                    f"of {cfg.max_audio_duration_seconds:.1f}s."
                ),
            )

    ext = _MIME_TO_EXT.get(detected_mime, "bin")
    return AudioValidationResult(
        is_valid=True,
        detected_mime_type=detected_mime,
        filename=f"patient_audio.{ext}",
        duration_seconds=measured_duration,
    )
