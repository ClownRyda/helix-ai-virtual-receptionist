"""
Speech-to-Text using faster-whisper (local, CTranslate2).
Accepts raw PCM audio bytes and returns transcribed text + detected language.
"""
from dataclasses import dataclass
import io
import numpy as np
import soundfile as sf
import structlog
from faster_whisper import WhisperModel
from config import settings

log = structlog.get_logger(__name__)

_model: WhisperModel | None = None


def get_model() -> WhisperModel:
    global _model
    if _model is None:
        # Use multilingual model when auto language detection is enabled.
        # .en-only models (base.en, small.en, etc.) cannot detect Spanish.
        model_name = (
            settings.whisper_model_multilingual
            if settings.auto_detect_language
            else settings.whisper_model
        )
        log.info("Loading Whisper model",
                 model=model_name,
                 device=settings.whisper_device,
                 multilingual=settings.auto_detect_language)
        _model = WhisperModel(
            model_name,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
        log.info("Whisper model loaded")
    return _model


@dataclass
class TranscribeResult:
    """Result of a Whisper transcription."""
    text: str
    language: str        # ISO 639-1 code detected by Whisper, e.g. 'en' or 'es'
    confidence: float    # language detection probability (0.0–1.0)


def transcribe_pcm(
    pcm_bytes: bytes,
    sample_rate: int = 16000,
    channels: int = 1,
    language: str | None = None,   # None = auto-detect
) -> TranscribeResult:
    """
    Transcribe raw PCM16 audio bytes to text.

    Args:
        pcm_bytes: Raw 16-bit signed PCM audio
        sample_rate: Audio sample rate (default 16000 Hz from Asterisk slin16)
        channels: Number of channels (1 = mono)
        language: Force a specific language code, or None for auto-detection

    Returns:
        TranscribeResult with text, detected language, and confidence.
    """
    if not pcm_bytes or len(pcm_bytes) < 1024:
        return TranscribeResult(text="", language="en", confidence=0.0)

    model = get_model()

    # Convert raw PCM bytes → numpy float32 array
    audio_np = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    # faster-whisper expects mono float32 at 16kHz
    if channels > 1:
        audio_np = audio_np.reshape(-1, channels).mean(axis=1)

    segments, info = model.transcribe(
        audio_np,
        beam_size=5,
        language=language,           # None = multilingual auto-detect
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        without_timestamps=True,
    )

    text = " ".join(seg.text.strip() for seg in segments).strip()
    result = TranscribeResult(
        text=text,
        language=info.language or "en",
        confidence=info.language_probability or 0.0,
    )
    if text:
        log.info("Transcribed",
                 text=text,
                 language=result.language,
                 confidence=round(result.confidence, 2),
                 duration=info.duration)
    return result


def transcribe_wav_file(wav_path: str, language: str | None = None) -> TranscribeResult:
    """Transcribe a WAV file on disk."""
    model = get_model()
    segments, info = model.transcribe(
        wav_path,
        beam_size=5,
        language=language,
        vad_filter=True,
        without_timestamps=True,
    )
    return TranscribeResult(
        text=" ".join(seg.text.strip() for seg in segments).strip(),
        language=info.language or "en",
        confidence=info.language_probability or 0.0,
    )
