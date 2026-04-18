"""
Silero VAD Engine — replaces simple RMS energy-based silence detection.

Uses Silero VAD (snakers4/silero-vad) for accurate, real-time voice activity
detection.  The model is a tiny (~2 MB) neural network that runs on CPU in
< 1 ms per 32 ms audio chunk — negligible overhead even on modest hardware.

Key design decisions:
  • We use FixedVADIterator (a buffer-aware wrapper around VADIterator) so
    that incoming PCM chunks of arbitrary length are handled correctly.
    Silero internally requires exactly 512 samples per call at 16 kHz;
    FixedVADIterator accumulates a buffer and drains it in 512-sample windows.
  • The model is loaded once at import-time and shared across all call
    handlers (it is stateless between reset_states() calls).
  • Each CallHandler gets its own SileroVADEngine instance with independent
    state via reset().
"""

import numpy as np
import torch
import structlog

log = structlog.get_logger(__name__)

# ── Silero model singleton ──────────────────────────────────────────────────
# Loaded once, reused across all calls.  Thread-safe for inference because
# each VADIterator carries its own hidden state copy.

_silero_model = None


def _load_model():
    global _silero_model
    if _silero_model is None:
        torch.set_num_threads(1)  # Silero is optimised for single-thread CPU
        _silero_model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            # trust_repo=True is required for non-interactive startup.
            # Without it, torch.hub prompts stdin with a trust confirmation
            # question when the model hasn't been cached yet. In a systemd
            # service there is no stdin, so the prompt blocks indefinitely
            # then raises EOFError, crashing the agent and causing the
            # ARI WebSocket to connect and immediately disconnect in a loop.
            trust_repo=True,
        )
        log.info("Silero VAD model loaded")
    return _silero_model


# ── FixedVADIterator ────────────────────────────────────────────────────────
# Adapted from the upstream whisper_streaming project (MIT licence).
# Buffers arbitrary-length audio and drains in 512-sample windows.

class _VADIterator:
    """Thin wrapper matching upstream Silero VADIterator API."""

    def __init__(
        self,
        model,
        threshold: float = 0.5,
        sampling_rate: int = 16000,
        min_silence_duration_ms: int = 500,
        speech_pad_ms: int = 100,
    ):
        self.model = model
        self.threshold = threshold
        self.sampling_rate = sampling_rate
        if sampling_rate not in (8000, 16000):
            raise ValueError("Silero VAD supports 8000 and 16000 Hz only")
        self.min_silence_samples = sampling_rate * min_silence_duration_ms / 1000
        self.speech_pad_samples = sampling_rate * speech_pad_ms / 1000
        self.reset_states()

    def reset_states(self):
        self.model.reset_states()
        self.triggered = False
        self.temp_end = 0
        self.current_sample = 0

    @torch.no_grad()
    def __call__(self, x, return_seconds: bool = False):
        if not torch.is_tensor(x):
            try:
                x = torch.Tensor(x)
            except Exception:
                raise TypeError("Audio cannot be cast to tensor")

        window_size_samples = len(x[0]) if x.dim() == 2 else len(x)
        self.current_sample += window_size_samples

        speech_prob = self.model(x, self.sampling_rate).item()

        # Cancel pending silence if speech resumes
        if speech_prob >= self.threshold and self.temp_end:
            self.temp_end = 0

        # Speech start
        if speech_prob >= self.threshold and not self.triggered:
            self.triggered = True
            speech_start = max(
                0, self.current_sample - self.speech_pad_samples - window_size_samples
            )
            return {
                "start": (
                    int(speech_start)
                    if not return_seconds
                    else round(speech_start / self.sampling_rate, 1)
                )
            }

        # Speech end (with hysteresis: threshold - 0.15)
        if speech_prob < (self.threshold - 0.15) and self.triggered:
            if not self.temp_end:
                self.temp_end = self.current_sample
            if self.current_sample - self.temp_end < self.min_silence_samples:
                return None
            else:
                speech_end = self.temp_end + self.speech_pad_samples - window_size_samples
                self.temp_end = 0
                self.triggered = False
                return {
                    "end": (
                        int(speech_end)
                        if not return_seconds
                        else round(speech_end / self.sampling_rate, 1)
                    )
                }

        return None


class _FixedVADIterator(_VADIterator):
    """Handles arbitrary-length audio chunks by buffering internally."""

    def reset_states(self):
        super().reset_states()
        self.buffer = np.array([], dtype=np.float32)

    def __call__(self, x, return_seconds: bool = False):
        self.buffer = np.append(self.buffer, x)
        ret = None
        while len(self.buffer) >= 512:
            r = super().__call__(self.buffer[:512], return_seconds=return_seconds)
            self.buffer = self.buffer[512:]
            if ret is None:
                ret = r
            elif r is not None:
                if "end" in r:
                    ret["end"] = r["end"]
                if "start" in r and "end" in ret:
                    del ret["end"]
        return ret


# ── Public API ──────────────────────────────────────────────────────────────

class SileroVADEngine:
    """
    Per-call VAD engine.  Create one instance per CallHandler.

    Usage:
        vad = SileroVADEngine(threshold=0.5, min_silence_ms=600)
        ...
        # Feed raw PCM16 bytes (signed 16-bit LE, 16 kHz mono)
        event = vad.process_chunk(pcm_bytes)
        # event is None, {"start": ...}, or {"end": ...}

    Call reset() between calls or when reusing the engine.
    """

    def __init__(
        self,
        threshold: float = 0.5,
        min_silence_ms: int = 600,
        speech_pad_ms: int = 100,
    ):
        model = _load_model()
        self._vad = _FixedVADIterator(
            model,
            threshold=threshold,
            sampling_rate=16000,
            min_silence_duration_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
        )
        self._is_speaking = False

    @property
    def is_speaking(self) -> bool:
        """True while the model believes the caller is speaking."""
        return self._is_speaking

    def process_chunk(self, pcm_bytes: bytes) -> dict | None:
        """
        Feed raw PCM16 (signed 16-bit LE, 16 kHz mono) bytes.

        Returns:
            None              — no state change
            {"start": <int>}  — speech just started (sample offset)
            {"end":   <int>}  — speech just ended   (sample offset)
        """
        if len(pcm_bytes) < 2:
            return None

        # Convert signed int16 PCM → float32 in [-1, 1]
        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        result = self._vad(samples, return_seconds=False)

        if result is not None:
            if "start" in result:
                self._is_speaking = True
            elif "end" in result:
                self._is_speaking = False

        return result

    def reset(self):
        """Reset all internal state — call between separate audio sessions."""
        self._vad.reset_states()
        self._is_speaking = False
