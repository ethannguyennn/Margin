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

from margin_relay.pipeline.transcribe import (
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
        if self.exc:
            raise self.exc
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
    t = GeminiTranscriber(client(delay=0.5), "m", timeout=0.01)
    with pytest.raises(TranscriptionError) as e:
        asyncio.run(t.transcribe(PCM, 16000))
    assert e.value.code == "stt_failed"


def test_api_error_raises_stt_failed():
    with pytest.raises(TranscriptionError):
        asyncio.run(GeminiTranscriber(client(exc=RuntimeError("boom")), "m").transcribe(PCM, 16000))


def test_mock_transcriber():
    assert asyncio.run(MockTranscriber().transcribe(PCM, 16000)) == "how tight is the m5 on the mounting bracket"
