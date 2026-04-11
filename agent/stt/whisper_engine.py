"""
Speech-to-Text using faster-whisper (local, CTranslate2).
Accepts raw PCM audio bytes and returns transcribed text.
"""
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
        log.info("Loading Whisper model", model=settings.whisper_model, device=settings.whisper_device)
        _model = WhisperModel(
            settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
        log.info("Whisper model loaded")
    return _model


def transcribe_pcm(pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1) -> str:
    """
    Transcribe raw PCM16 audio bytes to text.

    Args:
        pcm_bytes: Raw 16-bit signed PCM audio
        sample_rate: Audio sample rate (default 16000 Hz from Asterisk slin16)
        channels: Number of channels (1 = mono)

    Returns:
        Transcribed text string, empty string if nothing detected.
    """
    if not pcm_bytes or len(pcm_bytes) < 1024:
        return ""

    model = get_model()

    # Convert raw PCM bytes → numpy float32 array
    audio_np = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

    # faster-whisper expects mono float32 at 16kHz
    if channels > 1:
        audio_np = audio_np.reshape(-1, channels).mean(axis=1)

    segments, info = model.transcribe(
        audio_np,
        beam_size=5,
        language="en",
        vad_filter=True,                   # skip silence automatically
        vad_parameters={"min_silence_duration_ms": 500},
        without_timestamps=True,
    )

    text = " ".join(seg.text.strip() for seg in segments).strip()
    if text:
        log.info("Transcribed", text=text, language=info.language, duration=info.duration)
    return text


def transcribe_wav_file(wav_path: str) -> str:
    """Transcribe a WAV file on disk."""
    model = get_model()
    segments, info = model.transcribe(
        wav_path,
        beam_size=5,
        language="en",
        vad_filter=True,
        without_timestamps=True,
    )
    return " ".join(seg.text.strip() for seg in segments).strip()
