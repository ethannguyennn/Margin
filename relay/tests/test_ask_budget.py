"""The ask latency budget: Gemini retries fit inside ASK_BUDGET_S, and 429 / 5xx
from Gemini is retried after a pause without blaming the model's answer."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from specs_relay.pipeline.generate import GenerationUnavailable, GeminiGenerator
from specs_relay.pipeline.transcribe import GeminiTranscriber
from specs_relay.routes import ask

SETTINGS = SimpleNamespace(generate_timeout_s=6.5)
GOOD = SimpleNamespace(answerable=True, needs_clarification=False, glance="Torque M5 to 4 N-m", body="")


class FakeGenerator:
    def __init__(self, *outcomes):
        self.outcomes, self.feedback = list(outcomes), []

    async def generate(self, query, chunks, feedback=None):
        self.feedback.append(feedback)
        out = self.outcomes.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out


def pipeline(generator, ok=True):
    verified = SimpleNamespace(ok=True, citations=["c1"], reason=None)
    rejected = SimpleNamespace(ok=False, citations=[], reason="glance_too_long: 52 chars, the limit is 40")
    return SimpleNamespace(generator=generator, sanitize=lambda t: t,
                           verify=lambda draft, chunks: verified if ok else rejected)


RETRIEVED = SimpleNamespace(chunks=["chunk"])


def test_transient_gemini_error_is_retried_without_feedback(monkeypatch):
    monkeypatch.setattr(ask, "TRANSIENT_BACKOFF_S", 0)
    gen = FakeGenerator(GenerationUnavailable("generation unavailable: HTTP 429"), GOOD)
    out = asyncio.run(ask._answer(pipeline(gen), SETTINGS, "q", RETRIEVED, time.monotonic() + 7.5))
    assert out == ("Torque M5 to 4 N-m", "", ["c1"])
    assert gen.feedback == [None, None]  # a quota error says nothing about the answer


def test_retry_is_skipped_when_the_budget_is_spent():
    gen = FakeGenerator(GOOD, GOOD)
    # Verification fails, and only 0.5 s of budget is left: no second Gemini call.
    out = asyncio.run(ask._answer(pipeline(gen, ok=False), SETTINGS, "q", RETRIEVED, time.monotonic() + 0.5))
    assert out is None and len(gen.feedback) == 1


def test_attempt_timeout_is_capped_by_the_remaining_budget():
    class Slow:
        async def generate(self, query, chunks, feedback=None):
            await asyncio.sleep(5)

    start = time.monotonic()
    with pytest.raises(ask.Fail) as exc:
        asyncio.run(ask._answer(pipeline(Slow()), SETTINGS, "q", RETRIEVED, time.monotonic() + 1.2))
    assert exc.value.code == "llm_timeout"
    assert time.monotonic() - start < 2.5  # stopped at the budget, not at generate_timeout_s


def test_transient_error_twice_is_an_llm_timeout(monkeypatch):
    monkeypatch.setattr(ask, "TRANSIENT_BACKOFF_S", 0)
    gen = FakeGenerator(GenerationUnavailable("429"), GenerationUnavailable("429"))
    with pytest.raises(ask.Fail) as exc:
        asyncio.run(ask._answer(pipeline(gen), SETTINGS, "q", RETRIEVED, time.monotonic() + 7.5))
    assert exc.value.code == "llm_timeout"


@pytest.mark.parametrize("code, transient", [(429, True), (503, True), (500, True), (400, False), (None, False)])
def test_gemini_http_codes_map_to_transient_or_not(code, transient):
    class Boom(Exception):
        pass

    err = Boom("api")
    err.code = code

    async def raises(**kw):
        raise err

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=raises)))
    gen = GeminiGenerator(client, "model")
    with pytest.raises(Exception) as exc:
        asyncio.run(gen.generate("q", []))
    assert isinstance(exc.value, GenerationUnavailable) is transient
    assert bool(getattr(exc.value, "transient", False)) is transient


def test_client_timeouts_sit_just_inside_the_route_guards():
    s = SimpleNamespace(gemini_api_key=None, gemini_model_generate="g", gemini_model_transcribe="t",
                        generate_timeout_s=6.5, stt_timeout_s=4.5)
    client = object()
    assert GeminiGenerator.from_settings(s, client=client).timeout == 6.0
    assert GeminiTranscriber.from_settings(s, client=client).timeout == 4.0
