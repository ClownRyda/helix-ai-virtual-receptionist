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


def synthesize_pcm(text: str) -> bytes:
    """
    Synthesize text to raw PCM16 audio at 16kHz (slin16) for Asterisk.

    Args:
        text: Text to speak

    Returns:
        Raw 16-bit signed PCM bytes at 16000 Hz, mono.
    """
    if not text:
        return b""

    model_path = os.path.join(settings.piper_model_path, f"{settings.piper_model}.onnx")
    config_path = os.path.join(settings.piper_model_path, f"{settings.piper_model}.onnx.json")

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
