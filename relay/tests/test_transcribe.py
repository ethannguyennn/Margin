"""STT path on the recorded fixture: relay/tests/fixtures/m5_question.pcm is a
synthetic-voice "How tight is the M5 on the mounting bracket?" as raw 16 kHz
s16le mono PCM (3.27 s). No network here; see test_live_gemini.py."""

import asyncio
import builtins
import io
import wave
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from google.genai.errors import APIError

from specs_relay.pipeline.generate import TRANSIENT_CODES
from specs_relay.pipeline.transcribe import (
    GeminiTranscriber,
    MockTranscriber,
    TranscriptionError,
    pcm_to_wav,
)

PCM = (Path(__file__).parent / "fixtures" / "m5_question.pcm").read_bytes()


def test_fixture_is_headerless_16k_pcm():
    assert PCM[:4] != b"RIFF"
    assert len(PCM) % 2 == 0
    assert 1.0 < len(PCM) / 32000 < 8.0  # under MAX_AUDIO_SECONDS


def test_pcm_to_wav_has_44_byte_header_and_round_trips():
    wav = pcm_to_wav(PCM, 16000)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    assert len(wav) == 44 + len(PCM)
    with wave.open(io.BytesIO(wav)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
        assert w.readframes(w.getnframes()) == PCM


@pytest.mark.parametrize("bad", [b"", b"\x00\x01\x02"])
def test_pcm_to_wav_rejects_partial_frames(bad):
    with pytest.raises(TranscriptionError):
        pcm_to_wav(bad, 16000)


class FakeModels:
    def __init__(self, text="how tight is the M5 on the mounting bracket", delay=0.0, exc=None):
        self.text, self.delay, self.exc, self.requests = text, delay, exc, []

    async def generate_content(self, *, model, contents, config):
        self.requests.append(NS(model=model, contents=contents, config=config))
        await asyncio.sleep(self.delay)
        exc = self.exc.pop(0) if isinstance(self.exc, list) else self.exc
        if exc:
            raise exc
        return NS(text=self.text)


def client(**kw):
    return NS(aio=NS(models=FakeModels(**kw)))


def test_sends_inline_wav_and_never_touches_disk(monkeypatch):
    def no_open(*a, **k):
        raise AssertionError("audio must never be written to disk")

    monkeypatch.setattr(builtins, "open", no_open)
    cl = client(text="  how tight is the M5\n on the mounting bracket ")
    text = asyncio.run(GeminiTranscriber(cl, "model-from-config").transcribe(PCM, 16000))
    assert text == "how tight is the M5 on the mounting bracket"
    req = cl.aio.models.requests[0]
    assert req.model == "model-from-config"
    prompt, part = req.contents
    assert "verbatim" in prompt
    assert part.inline_data.mime_type == "audio/wav"
    assert part.inline_data.data[:4] == b"RIFF"
    assert len(part.inline_data.data) == 44 + len(PCM)


def test_timeout_raises_stt_failed():
    cl = client(delay=0.5)
    t = GeminiTranscriber(cl, "m", timeout=0.01)
    with pytest.raises(TranscriptionError) as e:
        asyncio.run(t.transcribe(PCM, 16000))
    assert e.value.code == "stt_failed"
    assert len(cl.aio.models.requests) <= 1


def test_coffee_vocabulary_is_sent_without_rewriting_spoken_units():
    cl = client(text="two pumps for the cappuccino at one hundred fifty degrees Fahrenheit")
    text = asyncio.run(GeminiTranscriber(cl, "m").transcribe(PCM, 16000))
    assert text == cl.aio.models.text
    prompt = cl.aio.models.requests[0].contents[0]
    for word in ("espresso", "cappuccino", "latte", "flat white", "americano", "mocha",
                 "pumps", "oz", "ppm", "Fahrenheit"):
        assert word in prompt
    assert "never add unheard words or convert numbers or units" in prompt
    assert "If there is no speech, output nothing" in prompt


def api_error(code):
    return APIError(code, {"error": {"message": "api"}})


@pytest.mark.parametrize("code", sorted(TRANSIENT_CODES))
def test_transient_error_then_success_returns_text(code):
    cl = client(text="  cleaning procedure  ", exc=[api_error(code), None])
    assert asyncio.run(GeminiTranscriber(cl, "m").transcribe(PCM, 16000)) == "cleaning procedure"
    assert len(cl.aio.models.requests) == 2


def test_transient_error_twice_raises_stt_failed():
    cl = client(exc=[api_error(429), api_error(429)])
    with pytest.raises(TranscriptionError) as e:
        asyncio.run(GeminiTranscriber(cl, "m").transcribe(PCM, 16000))
    assert e.value.code == "stt_failed"
    assert len(cl.aio.models.requests) == 2


def test_bad_request_does_not_retry():
    cl = client(exc=[api_error(400), None])
    with pytest.raises(TranscriptionError):
        asyncio.run(GeminiTranscriber(cl, "m").transcribe(PCM, 16000))
    assert len(cl.aio.models.requests) == 1


def test_transient_error_does_not_retry_without_time_for_backoff():
    cl = client(delay=0.02, exc=[api_error(429), None])
    with pytest.raises(TranscriptionError):
        asyncio.run(GeminiTranscriber(cl, "m", timeout=0.41).transcribe(PCM, 16000))
    assert len(cl.aio.models.requests) == 1


def test_retry_uses_remaining_timeout(monkeypatch):
    timeouts = []
    wait_for = asyncio.wait_for

    async def record_timeout(coro, *, timeout):
        timeouts.append(timeout)
        return await wait_for(coro, timeout=timeout)

    monkeypatch.setattr(asyncio, "wait_for", record_timeout)
    cl = client(delay=0.1, exc=[api_error(429), None])
    with pytest.raises(TranscriptionError, match="transcription timed out"):
        asyncio.run(GeminiTranscriber(cl, "m", timeout=0.55).transcribe(PCM, 16000))
    assert len(cl.aio.models.requests) == 2
    assert 0 < timeouts[1] < 0.1


def test_api_error_raises_stt_failed():
    with pytest.raises(TranscriptionError):
        asyncio.run(GeminiTranscriber(client(exc=RuntimeError("boom")), "m").transcribe(PCM, 16000))


def test_mock_transcriber():
    assert asyncio.run(MockTranscriber().transcribe(PCM, 16000)) == "how tight is the m5 on the mounting bracket"
