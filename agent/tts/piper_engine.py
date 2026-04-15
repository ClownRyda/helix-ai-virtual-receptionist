"""
Text-to-Speech using Piper (local neural TTS).
Returns raw PCM16 audio bytes suitable for injection into Asterisk RTP.
"""
import subprocess
import tempfile
import os
import struct
import structlog
from config import settings

log = structlog.get_logger(__name__)

# Piper outputs 22050 Hz PCM by default; Asterisk slin16 expects 16000 Hz.
# We resample in synthesize_pcm() using scipy.
PIPER_SAMPLE_RATE = 22050
ASTERISK_SAMPLE_RATE = 16000


# Maps language code → settings attribute holding the Piper model name.
# If the attribute resolves to an empty string, espeak-ng fallback is used.
LANG_MODEL_ATTR = {
    "en": "piper_model",
    "es": "piper_model_es",
    "fr": "piper_model_fr",
    "it": "piper_model_it",
    "de": "piper_model_de",
    "ro": "piper_model_ro",
    "he": "piper_model_he",   # empty string — routes to espeak-ng
}

# espeak-ng voice tags for languages without Piper support
ESPEAK_VOICES = {
    "he": "he",  # Hebrew
}


def _get_model_name(language: str) -> str:
    """Resolve Piper model name for a language code. Returns '' if not configured."""
    attr = LANG_MODEL_ATTR.get(language, "piper_model")
    return getattr(settings, attr, "") or ""


def synthesize_pcm(text: str, language: str = "en") -> bytes:
    """
    Synthesize text to raw PCM16 audio at 16kHz (slin16) for Asterisk.

    Selects the correct Piper voice for the detected language.
    Falls back to espeak-ng for languages without a Piper model (e.g. Hebrew).

    Args:
        text: Text to speak
        language: ISO 639-1 language code

    Returns:
        Raw 16-bit signed PCM bytes at 16000 Hz, mono.
    """
    if not text:
        return b""

    model_name = _get_model_name(language)

    # If no Piper model, try espeak-ng fallback
    if not model_name:
        if language in ESPEAK_VOICES:
            return _synthesize_espeak(text, ESPEAK_VOICES[language])
        # Unknown language — fall back to English Piper
        log.warning("No TTS model for language, falling back to English", lang=language)
        model_name = settings.piper_model

    model_path = os.path.join(settings.piper_model_path, f"{model_name}.onnx")
    config_path = os.path.join(settings.piper_model_path, f"{model_name}.onnx.json")

    if not os.path.exists(model_path):
        log.error("Piper model not found", path=model_path)
        return _fallback_silence(seconds=1)

    with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [
                "piper",
                "--model", model_path,
                "--config", config_path,
                "--output-raw",
                "--output-file", tmp_path,
            ],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=15,
        )

        if result.returncode != 0:
            log.error("Piper TTS error", stderr=result.stderr.decode())
            return _fallback_silence(seconds=1)

        with open(tmp_path, "rb") as f:
            raw_pcm = f.read()

        # Resample from PIPER_SAMPLE_RATE to ASTERISK_SAMPLE_RATE
        resampled = _resample_pcm(raw_pcm, PIPER_SAMPLE_RATE, ASTERISK_SAMPLE_RATE)
        log.info("TTS synthesized", chars=len(text), bytes=len(resampled))
        return resampled

    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _resample_pcm(pcm_bytes: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Resample PCM16 audio from src_rate to dst_rate using scipy."""
    import numpy as np
    from scipy.signal import resample_poly
    from math import gcd

    if src_rate == dst_rate:
        return pcm_bytes

    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
    g = gcd(src_rate, dst_rate)
    up, down = dst_rate // g, src_rate // g
    resampled = resample_poly(audio, up, down)
    resampled = np.clip(resampled, -32768, 32767).astype(np.int16)
    return resampled.tobytes()


def _fallback_silence(seconds: float) -> bytes:
    """Return silent PCM16 audio for the given duration."""
    num_samples = int(ASTERISK_SAMPLE_RATE * seconds)
    return b"\x00\x00" * num_samples


def _synthesize_espeak(text: str, voice: str) -> bytes:
    """
    Synthesize text using espeak-ng (fallback for languages without a Piper model).
    Outputs 16kHz mono PCM16 directly — no resampling needed.

    Args:
        text: Text to speak
        voice: espeak-ng voice tag (e.g. 'he' for Hebrew)

    Returns:
        Raw PCM16 bytes at 16000 Hz, mono.
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [
                "espeak-ng",
                "-v", voice,
                "-r", "160",        # words per minute (slightly slower for clarity)
                "-a", "180",        # amplitude (0-200)
                "--stdout",
            ],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=15,
        )

        if result.returncode != 0:
            log.error("espeak-ng TTS error", voice=voice, stderr=result.stderr.decode())
            return _fallback_silence(seconds=1)

        # espeak-ng --stdout outputs a WAV file; extract the PCM data
        raw_wav = result.stdout
        if len(raw_wav) < 44:
            return _fallback_silence(seconds=1)

        # Strip 44-byte WAV header to get raw PCM
        raw_pcm = raw_wav[44:]

        # espeak-ng outputs at 22050 Hz by default; resample to 16000 Hz
        resampled = _resample_pcm(raw_pcm, 22050, ASTERISK_SAMPLE_RATE)
        log.info("espeak-ng TTS synthesized", voice=voice, chars=len(text), bytes=len(resampled))
        return resampled

    except FileNotFoundError:
        log.error("espeak-ng not found. Install with: apt-get install espeak-ng")
        return _fallback_silence(seconds=1)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
