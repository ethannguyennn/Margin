"""Speech to text. Input is raw PCM: 16 kHz, signed 16-bit LE, mono.

The PCM is wrapped in a WAV container in memory (stdlib ``wave``, 44-byte
header) and sent inline. Audio never touches disk, not even while debugging.
"""

from __future__ import annotations

import asyncio
import io
import wave
from typing import Any

from . import SttFailed

TRANSCRIBE_TIMEOUT_S = 4.0
SAMPLE_WIDTH = 2  # s16le

TRANSCRIBE_PROMPT = (
    "Transcribe the speech in this audio verbatim. Output only the words spoken, "
    "exactly as heard: no punctuation cleanup, no corrections, no summary, no "
    "interpretation. Keep part codes and numbers as spoken (for example 'M5', "
    "'four newton meters'). If there is no speech, output nothing."
)


class TranscriptionError(SttFailed):
    pass


def pcm_to_wav(pcm: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """Wrap raw s16le PCM in a WAV container, in memory."""
    if not pcm or len(pcm) % (SAMPLE_WIDTH * channels):
        raise TranscriptionError("PCM must be non-empty whole s16le frames")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


class GeminiTranscriber:
    def __init__(self, client: Any, model: str, timeout: float = TRANSCRIBE_TIMEOUT_S):
        if not model:
            raise ValueError("GEMINI_MODEL_TRANSCRIBE is not set")
        self.client, self.model, self.timeout = client, model, timeout

    @classmethod
    def from_settings(cls, settings: Any, client: Any = None) -> "GeminiTranscriber":
        from .generate import gemini_client

        # Just under the route's outer guard (STT_TIMEOUT_S); see GeminiGenerator.from_settings.
        timeout = max(1.0, float(getattr(settings, "stt_timeout_s", TRANSCRIBE_TIMEOUT_S + 1)) - 0.5)
        return cls(client or gemini_client(settings.gemini_api_key), settings.gemini_model_transcribe,
                   timeout=timeout)

    async def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        from google.genai import types

        audio = types.Part.from_bytes(data=pcm_to_wav(pcm, sample_rate), mime_type="audio/wav")
        try:
            resp = await asyncio.wait_for(
                self.client.aio.models.generate_content(
                    model=self.model,
                    contents=[TRANSCRIBE_PROMPT, audio],
                    config=types.GenerateContentConfig(temperature=0.0),
                ),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError as e:
            raise TranscriptionError("transcription timed out") from e
        except Exception as e:
            raise TranscriptionError(f"transcription failed: {type(e).__name__}") from e
        return " ".join((resp.text or "").split())


class MockTranscriber:
    """Canned transcript so the pipeline runs with no API key."""

    def __init__(self, text: str = "how tight is the m5 on the mounting bracket"):
        self.text = text

    async def transcribe(self, pcm: bytes, sample_rate: int) -> str:
        pcm_to_wav(pcm, sample_rate)  # same input validation as the real path
        return self.text
