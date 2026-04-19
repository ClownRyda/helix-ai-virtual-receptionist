"""
Text-to-Speech using Kokoro (local neural TTS, 82M parameters).
Returns raw PCM16 audio bytes at 16 kHz suitable for Asterisk slin16 RTP.

Kokoro supports: American English (a), British English (b), Spanish (e),
                 French (f), Italian (i).
Languages without native Kokoro support (DE, RO, HE) fall back to espeak-ng.

Install:
    pip install kokoro>=0.9.2 soundfile
    apt-get install -y espeak-ng
"""
import io
import struct
import subprocess
import numpy as np
import structlog
from config import settings

log = structlog.get_logger(__name__)

# Kokoro outputs float32 audio at 24000 Hz. Asterisk slin16 expects 16000 Hz.
KOKORO_SAMPLE_RATE = 24000
ASTERISK_SAMPLE_RATE = 16000

# Kokoro lang_code values per ISO 639-1 language code.
# American English preferred; British available as alternate.
KOKORO_LANG_CODE = {
    "en": "a",   # American English
    "es": "e",   # Spanish
    "fr": "f",   # French
    "it": "i",   # Italian
}

# Default Kokoro voice per language (high-quality, neutral voices).
# Full voice list: https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md
KOKORO_VOICE = {
    "en": "af_heart",    # American English female — warm, natural
    "es": "ef_dora",     # Spanish female
    "fr": "ff_siwis",    # French female
    "it": "if_sara",     # Italian female
}

# Slightly slower English pacing sounds less synthetic on phone audio.
KOKORO_SPEED = {
    "en": 0.92,
    "es": 0.98,
    "fr": 0.98,
    "it": 0.98,
}

# Brief pauses between Kokoro chunks avoid the hard stitched-together sound.
KOKORO_CHUNK_PAUSE_MS = {
    "en": 120,
    "es": 80,
    "fr": 80,
    "it": 80,
}

# espeak-ng voice tags for languages without Kokoro support
ESPEAK_VOICES = {
    "de": "de",    # German
    "ro": "ro",    # Romanian
    "he": "he",    # Hebrew
}

# Lazy-loaded pipelines keyed by lang_code (e.g. "a", "e", "f", "i").
# KPipeline is loaded on first use per language to avoid startup latency.
_pipelines: dict = {}


def _get_pipeline(lang_code: str):
    """Return a cached KPipeline for the given Kokoro lang_code."""
    if lang_code not in _pipelines:
        try:
            from kokoro import KPipeline  # type: ignore
            _pipelines[lang_code] = KPipeline(lang_code=lang_code)
            log.info("Kokoro pipeline loaded", lang_code=lang_code)
        except ImportError:
            log.error(
                "Kokoro not installed. Run: pip install kokoro>=0.9.2 soundfile"
            )
            return None
        except Exception as exc:
            log.error("Failed to load Kokoro pipeline", lang_code=lang_code, error=str(exc))
            return None
    return _pipelines[lang_code]


def synthesize_pcm(text: str, language: str = "en", voice_override: str = "") -> bytes:
    """
    Synthesize text to raw PCM16 audio at 16 kHz (slin16) for Asterisk.

    Uses Kokoro for EN/ES/FR/IT; espeak-ng for DE/RO/HE.

    Args:
        text:     Text to speak.
        language: ISO 639-1 language code ("en", "es", "fr", "it", "de", "ro", "he").
        voice_override: Explicit Kokoro voice name for this synthesis call.

    Returns:
        Raw 16-bit signed PCM bytes at 16000 Hz, mono.
    """
    if not text:
        return b""

    # Route to espeak-ng for languages without Kokoro support
    if language in ESPEAK_VOICES:
        return _synthesize_espeak(text, ESPEAK_VOICES[language])

    lang_code = KOKORO_LANG_CODE.get(language, "a")
    voice     = KOKORO_VOICE.get(language, "af_heart")

    # Allow per-language voice override from settings
    configured_voice_override = getattr(settings, f"kokoro_voice_{language}", "") or ""
    if configured_voice_override:
        voice = configured_voice_override
    if voice_override:
        voice = voice_override

    pipeline = _get_pipeline(lang_code)
    if pipeline is None:
        log.warning("Kokoro unavailable, falling back to espeak-ng English", lang=language)
        return _synthesize_espeak(text, "en")

    try:
        audio_chunks = []
        speed = KOKORO_SPEED.get(language, 1.0)
        generator = pipeline(text, voice=voice, speed=speed, split_pattern=r"[.!?;:]+")
        for _gs, _ps, audio in generator:
            if audio is not None and len(audio) > 0:
                audio_chunks.append(audio)

        if not audio_chunks:
            log.warning("Kokoro produced no audio", language=language)
            return _fallback_silence(seconds=1)

        # Add a small pause between chunks so speech sounds less abrupt.
        pause_ms = KOKORO_CHUNK_PAUSE_MS.get(language, 0)
        if pause_ms and len(audio_chunks) > 1:
            pause_samples = int(KOKORO_SAMPLE_RATE * (pause_ms / 1000.0))
            pause = np.zeros(pause_samples, dtype=np.float32)
            stitched = []
            for i, chunk in enumerate(audio_chunks):
                stitched.append(chunk)
                if i < len(audio_chunks) - 1:
                    stitched.append(pause)
            combined = np.concatenate(stitched).astype(np.float32)
        else:
            combined = np.concatenate(audio_chunks).astype(np.float32)

        # Resample from 24000 Hz to 16000 Hz
        resampled = _resample_float32(combined, KOKORO_SAMPLE_RATE, ASTERISK_SAMPLE_RATE)

        # Convert float32 [-1, 1] to int16
        pcm16 = (np.clip(resampled, -1.0, 1.0) * 32767).astype(np.int16)

        result = pcm16.tobytes()
        log.info("Kokoro TTS synthesized", lang=language, voice=voice, chars=len(text), bytes=len(result))
        return result

    except Exception as exc:
        log.error("Kokoro synthesis error", language=language, error=str(exc))
        return _fallback_silence(seconds=1)


def _resample_float32(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Resample a float32 audio array from src_rate to dst_rate using scipy."""
    if src_rate == dst_rate:
        return audio
    from scipy.signal import resample_poly
    from math import gcd
    g = gcd(src_rate, dst_rate)
    up, down = dst_rate // g, src_rate // g
    return resample_poly(audio, up, down).astype(np.float32)


def _fallback_silence(seconds: float) -> bytes:
    """Return silent PCM16 audio for the given duration at ASTERISK_SAMPLE_RATE."""
    num_samples = int(ASTERISK_SAMPLE_RATE * seconds)
    return b"\x00\x00" * num_samples


def _synthesize_espeak(text: str, voice: str) -> bytes:
    """
    Synthesize text using espeak-ng for languages without Kokoro support.
    Outputs raw PCM16 at 16 kHz mono.

    Args:
        text:  Text to speak.
        voice: espeak-ng voice tag (e.g. "de", "ro", "he").

    Returns:
        Raw 16-bit signed PCM bytes at 16000 Hz, mono.
    """
    try:
        result = subprocess.run(
            [
                "espeak-ng",
                "-v", voice,
                "-r", "160",       # words per minute (slightly slower for clarity)
                "-a", "180",       # amplitude (0–200)
                "--stdout",
            ],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=15,
        )

        if result.returncode != 0:
            log.error("espeak-ng error", voice=voice, stderr=result.stderr.decode())
            return _fallback_silence(seconds=1)

        raw_wav = result.stdout
        if len(raw_wav) < 44:
            return _fallback_silence(seconds=1)

        # Parse WAV header properly to find data offset
        import wave
        try:
            with wave.open(io.BytesIO(raw_wav)) as wf:
                sample_rate = wf.getframerate()
                raw_pcm = wf.readframes(wf.getnframes())
        except Exception:
            # Fallback: strip standard 44-byte header
            raw_pcm = raw_wav[44:]
            sample_rate = 22050

        # Convert from bytes to int16 numpy, resample to 16000 Hz
        audio = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32)
        if sample_rate != ASTERISK_SAMPLE_RATE:
            from scipy.signal import resample_poly
            from math import gcd
            g = gcd(sample_rate, ASTERISK_SAMPLE_RATE)
            audio = resample_poly(audio, ASTERISK_SAMPLE_RATE // g, sample_rate // g)

        pcm16 = np.clip(audio, -32768, 32767).astype(np.int16)
        result_bytes = pcm16.tobytes()
        log.info("espeak-ng TTS synthesized", voice=voice, chars=len(text), bytes=len(result_bytes))
        return result_bytes

    except FileNotFoundError:
        log.error("espeak-ng not found. Install: apt-get install espeak-ng")
        return _fallback_silence(seconds=1)
    except Exception as exc:
        log.error("espeak-ng error", voice=voice, error=str(exc))
        return _fallback_silence(seconds=1)
