"""M4 acceptance through Part 3's real /v1/ask route: Part 4's real intent,
verify and sanitize, with a fake retriever (fixed scores) and a scripted
generator (call counter). No network, no database."""

import base64
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from margin_relay.config import Settings
from margin_relay.main import Pipeline, _adapt_intent, create_app
from margin_relay.pipeline import mock
from margin_relay.pipeline.intent import classify_intent, deviation_text
from margin_relay.pipeline.sanitize import sanitize
from margin_relay.pipeline.transcribe import MockTranscriber
from margin_relay.pipeline.verify import verify
from margin_relay.schemas import Draft, RetrievalResult

from test_generate import CHUNKS, GOOD, HALLUCINATED

M5 = "how tight is the m5 on the mounting bracket"
OFF_DOC = "what is the wifi password"


class FakeRetriever:
    """On-document question: strong signals. Anything else: below both thresholds."""

    async def retrieve(self, query, revision):
        if "m5" in query.lower():
            return RetrievalResult(chunks=CHUNKS, best_sim=0.82, best_rrf=0.032)
        return RetrievalResult(chunks=CHUNKS[:2], best_sim=0.21, best_rrf=0.0164)

    async def steps_for(self, doc_id, revision):
        return []


class ScriptedGenerator:
    def __init__(self, *drafts):
        self.drafts, self.calls = list(drafts), 0

    async def generate(self, query, chunks, feedback=None):
        self.calls += 1
        return Draft.model_validate(self.drafts[min(self.calls, len(self.drafts)) - 1])


def client_for(gen):
    p = Pipeline(transcriber=MockTranscriber(), classify=_adapt_intent(classify_intent, deviation_text),
                 retriever=FakeRetriever(), generator=gen, verify=verify, sanitize=sanitize,
                 notifier=mock.MockNotifier(), db=mock.MockDB(), real_db=False,
                 min_sim=0.60, min_rrf=0.030)
    settings = Settings(_env_file=None, mock_mode=False, sentry_dsn_relay="")
    return TestClient(create_app(settings, p))


def ask(c, text=None, audio=None, context=None):
    body = {"session_id": str(uuid.uuid4()), "text": text, **({"context": context} if context else {})}
    if audio is not None:
        body = {"session_id": body["session_id"], "audio": {
            "format": "pcm_s16le", "sample_rate": 16000, "channels": 1,
            "data_b64": base64.b64encode(audio).decode()}}
    r = c.post("/v1/ask", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_off_document_question_returns_not_found_without_llm_call():
    gen = ScriptedGenerator(GOOD)
    with client_for(gen) as c:
        out = ask(c, OFF_DOC)
    assert out["outcome"] == "not_found"
    assert gen.calls == 0
    assert out["verified"] is False and out["citations"] == []
    assert out["glance"] == "Not in approved SOPs"


def test_forced_hallucination_is_caught_and_never_displayed():
    gen = ScriptedGenerator(HALLUCINATED)
    with client_for(gen) as c:
        out = ask(c, M5)
    assert gen.calls == 2                       # one retry with the verifier's reason
    assert out["outcome"] == "not_found"
    assert out["verified"] is False
    assert "5 N-m" not in out["glance"] + out["body"]


def test_verified_answer_carries_renderable_citation():
    with client_for(ScriptedGenerator(GOOD)) as c:
        out = ask(c, M5)
    assert out["outcome"] == "answered" and out["verified"] is True
    assert out["source"] == "SOP-114 Sec 4.2 rev C"
    cite = out["citations"][0]
    assert {k: cite[k] for k in ("chunk_id", "doc_id", "revision", "section")} == {
        "chunk_id": "SOP-114:C:4.2", "doc_id": "SOP-114", "revision": "C", "section": "4.2"}
    assert out["glance"].isascii() and len(out["glance"]) <= 60


def test_audio_path_with_recorded_fixture():
    pcm = (Path(__file__).parent / "fixtures" / "m5_question.pcm").read_bytes()
    with client_for(ScriptedGenerator(GOOD)) as c:
        out = ask(c, audio=pcm)
    assert out["transcript"] == M5
    assert out["outcome"] == "answered"


@pytest.mark.parametrize("text, intent", [
    ("what was that torque spec", "question"),
    ("say that again", "repeat"),  # outside a task it stays v1 repeat (BUILD-PLAN-V2 §3)
    ("what was that", "repeat"),
    ("log a deviation the bracket hole is out of round", "deviation"),
])
def test_real_intent_routes(text, intent):
    with client_for(ScriptedGenerator(GOOD)) as c:
        assert ask(c, text)["intent"] == intent


def test_say_that_again_inside_a_task_is_the_repeat_command():
    with client_for(ScriptedGenerator(GOOD)) as c:
        out = ask(c, "say that again", context={"doc_id": "SOP-114", "step_id": "SOP-114:C:4.2"})
    assert (out["intent"], out["outcome"], out["command"]) == ("command", "command", "repeat")
