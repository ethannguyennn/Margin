"""Part 3 route + orchestration tests, all under MOCK_MODE=1 (no DB, no Gemini)."""

from __future__ import annotations

import base64
import uuid

import pytest
from pydantic import ValidationError

from _relay_helpers import ask, make_client, sid
from margin_relay.pipeline import DbDown, SttFailed
from margin_relay.pipeline.mock import MockGenerator
from margin_relay.schemas import (
    NOT_FOUND_BODY,
    NOT_FOUND_GLANCE,
    AskResponse,
    Draft,
    DraftCitation,
    Latency,
    RetrievalResult,
    Step,
)

TORQUE = "how tight is the m5 on the mounting bracket"


@pytest.fixture
def client_app():
    return make_client()


@pytest.fixture
def client(client_app):
    return client_app[0]


def pcm_b64(seconds: float, rate: int = 16000) -> str:
    return base64.b64encode(b"\x00\x00" * int(seconds * rate)).decode()


def audio_req(seconds: float) -> dict:
    return {"session_id": sid(), "audio": {"format": "pcm_s16le", "sample_rate": 16000,
                                           "channels": 1, "data_b64": pcm_b64(seconds)}}


# --- health -------------------------------------------------------------------------


def test_health_mock(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "mock": True, "db": "mock", "version": "0.1.0"}
    assert r.headers["x-trace-id"]


# --- the fixture set Part 2 mocks on the app side ----------------------------------------


def test_answered_torque(client):
    r = ask(client, TORQUE)
    assert r.status_code == 200
    b = r.json()
    assert b["outcome"] == "answered" and b["intent"] == "question" and b["verified"] is True
    assert b["glance"] == "Step 4.2: torque M5 to 4 N-m"
    assert b["source"] == "SOP-114 Sec 4.2 rev C"
    c = b["citations"][0]
    assert (c["chunk_id"], c["doc_id"], c["revision"], c["section"]) == (
        "SOP-114:C:4.2", "SOP-114", "C", "4.2")
    assert "4 N-m" in c["quote"]
    assert b["walkthrough"] is None
    assert set(b["latency_ms"]) == {"stt", "embed", "retrieve", "generate", "verify", "total"}
    assert b["latency_ms"]["total"] >= b["latency_ms"]["generate"] > 0
    assert len(b["trace_id"]) == 32


def test_walkthrough_returns_every_step(client):
    b = ask(client, "walk me through the bracket assembly").json()
    assert b["intent"] == "walkthrough" and b["outcome"] == "answered" and b["verified"] is True
    w = b["walkthrough"]
    assert (w["doc_id"], w["revision"], w["total"], w["index"]) == ("SOP-114", "C", 7, 0)
    assert [s["label"] for s in w["steps"]] == [f"4.{i}" for i in range(1, 8)]
    assert all(len(s["glance"]) <= 60 and len(s["body"]) <= 450 for s in w["steps"])
    assert w["steps"][1]["step_id"] == "SOP-114:C:4.2"
    assert b["glance"] == "Mounting Bracket Assembly, 7 steps"
    assert b["source"] == "SOP-114 Sec 4.1 rev C"
    assert len(b["citations"]) == 7


def test_answered_clean_long_body(client):
    b = ask(client, "how do i clean and disinfect the housing").json()
    assert b["outcome"] == "answered" and b["source"].startswith("SOP-120 Sec 4.3 rev B")
    assert 300 < len(b["body"]) <= 450  # long enough to paginate on the lens


def test_not_found_without_llm_call(client_app):
    client, app = client_app
    gen = app.state.pipeline.generator
    b = ask(client, "where is the good coffee").json()
    assert b["outcome"] == "not_found"
    assert (b["glance"], b["body"]) == (NOT_FOUND_GLANCE, NOT_FOUND_BODY)
    assert b["citations"] == [] and b["verified"] is False and b["source"] == ""
    assert gen.calls == 0  # the gate refused before the LLM
    assert b["latency_ms"]["generate"] == 0


def test_logged_deviation(client_app):
    client, app = client_app
    r = ask(client, "log deviation bracket arrived pre-drilled",
            context={"doc_id": "SOP-114", "step_id": "SOP-114:C:4.2"})
    b = r.json()
    assert r.status_code == 200
    assert b["intent"] == "deviation" and b["outcome"] == "logged"
    assert b["glance"] == "Deviation DEV-0001 logged"
    assert b["source"] == "SOP-114 Sec 4.2 rev C"
    assert b["body"] == ("Deviation DEV-0001 recorded against SOP-114 Sec 4.2 rev C. "
                         "Supervisor alert sent.")
    row = app.state.pipeline.db.deviations[-1]
    assert row["text"] == "bracket arrived pre-drilled"  # trigger phrase stripped
    assert (row["doc_id"], row["step_id"], row["notified"]) == ("SOP-114", "SOP-114:C:4.2", True)


def test_error_llm_timeout(client):
    r = ask(client, "boom")
    assert r.status_code == 504
    b = r.json()
    assert b["outcome"] == "error" and b["error"]["code"] == "llm_timeout"
    assert set(b) == {"trace_id", "outcome", "error"} and b["trace_id"]


# --- trace_id on every response -------------------------------------------------------


@pytest.mark.parametrize("method,path,body,status", [
    ("post", "/v1/ask", {"session_id": "not-a-uuid", "text": "x"}, 400),
    ("post", "/v1/ask", {"text": "no session"}, 400),
    ("post", "/v1/ask", "not json", 400),
    ("get", "/v1/nope", None, 404),
    ("post", "/v1/health", None, 405),
])
def test_errors_carry_trace_id(client, method, path, body, status):
    kw = {"content": body} if isinstance(body, str) else ({"json": body} if body else {})
    r = getattr(client, method)(path, **kw)
    assert r.status_code == status
    b = r.json()
    assert b["outcome"] == "error" and b["trace_id"] and b["error"]["code"] == "bad_request"
    assert r.headers["x-trace-id"] == b["trace_id"]


def test_unhandled_exception_is_contract_shaped(client_app):
    client, app = client_app

    def boom(_t):
        raise RuntimeError("bug")

    app.state.pipeline.classify = boom
    r = ask(client, TORQUE)
    assert r.status_code == 500
    b = r.json()
    assert b["outcome"] == "error" and b["error"]["code"] == "internal" and b["trace_id"]


# --- request validation ------------------------------------------------------------------


def test_exactly_one_of_audio_or_text(client):
    both = audio_req(1) | {"text": "hi"}
    neither = {"session_id": sid()}
    blank = {"session_id": sid(), "text": "   "}
    for body in (both, neither, blank):
        r = client.post("/v1/ask", json=body)
        assert r.status_code == 400 and r.json()["error"]["code"] == "bad_request"


def test_audio_over_max_seconds_rejected(client_app):
    client, app = client_app
    r = client.post("/v1/ask", json=audio_req(8.5))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_request" and "8" in r.json()["error"]["message"]


def test_audio_bad_base64_rejected(client):
    req = audio_req(1)
    req["audio"]["data_b64"] = "@@not base64@@"
    assert client.post("/v1/ask", json=req).status_code == 400


def test_audio_path_transcribes(client):
    r = client.post("/v1/ask", json=audio_req(2.0))
    b = r.json()
    assert r.status_code == 200 and b["transcript"] == TORQUE and b["outcome"] == "answered"
    assert b["latency_ms"]["stt"] > 0


def test_audio_format_must_match_contract(client):
    req = audio_req(1)
    req["audio"]["sample_rate"] = 44100
    assert client.post("/v1/ask", json=req).status_code == 400


def test_stt_failure_maps_to_stt_failed(client_app):
    client, app = client_app

    class Broken:
        async def transcribe(self, pcm, sample_rate):
            raise SttFailed("mic noise")

    app.state.pipeline.transcriber = Broken()
    r = client.post("/v1/ask", json=audio_req(1))
    assert r.status_code == 502 and r.json()["error"]["code"] == "stt_failed"


# --- repeat ------------------------------------------------------------------------------


def test_repeat_resends_last_answer_without_pipeline(client_app):
    client, app = client_app
    s = sid()
    assert ask(client, "say that again", s).json()["outcome"] == "not_found"
    first = ask(client, TORQUE, s).json()
    calls = (app.state.pipeline.retriever.calls, app.state.pipeline.generator.calls)
    again = ask(client, "say that again", s).json()
    assert again["intent"] == "repeat" and again["outcome"] == "answered"
    assert again["glance"] == first["glance"] and again["citations"] == first["citations"]
    assert again["trace_id"] != first["trace_id"]
    assert (app.state.pipeline.retriever.calls, app.state.pipeline.generator.calls) == calls


def test_unknown_intent_is_not_found(client_app):
    client, app = client_app
    app.state.pipeline.classify = lambda t: __import__(
        "margin_relay.schemas", fromlist=["IntentResult"]).IntentResult(intent="unknown", text="")
    assert ask(client, "uh").json()["outcome"] == "not_found"
    assert app.state.pipeline.retriever.calls == 0


# --- verify + retry: unverified text is never returned ----------------------------------


class ScriptedGenerator:
    def __init__(self, *drafts):
        self.drafts, self.calls, self.feedback = list(drafts), 0, []

    async def generate(self, query, chunks, feedback=None):
        self.calls += 1
        self.feedback.append(feedback)
        d = self.drafts.pop(0)
        if isinstance(d, Exception):
            raise d
        return d


GOOD = Draft(answerable=True, glance="Torque M5 to 4 N-m", body="Torque to 4 N-m.",
             citations=[DraftCitation(chunk_id="SOP-114:C:4.2",
                                      quote="Torque all four M5 bracket screws to 4 N-m")])
HALLUCINATED = Draft(answerable=True, glance="Torque M5 to 5 N-m", body="Torque to 5 N-m.",
                     citations=[DraftCitation(chunk_id="SOP-114:C:4.2",
                                              quote="Torque all four M5 bracket screws to 5 N-m")])
WRONG_CHUNK = Draft(answerable=True, glance="x", body="y",
                    citations=[DraftCitation(chunk_id="SOP-999:Z:1", quote="anything")])


def test_verify_failure_retries_once_with_reason(client_app):
    client, app = client_app
    gen = app.state.pipeline.generator = ScriptedGenerator(HALLUCINATED, GOOD)
    b = ask(client, TORQUE).json()
    assert b["outcome"] == "answered" and b["verified"] is True and b["glance"] == GOOD.glance
    assert gen.calls == 2 and gen.feedback[0] is None and "quote not found" in gen.feedback[1]


def test_second_verify_failure_is_not_found(client_app):
    client, app = client_app
    gen = app.state.pipeline.generator = ScriptedGenerator(HALLUCINATED, WRONG_CHUNK)
    b = ask(client, TORQUE).json()
    assert b["outcome"] == "not_found" and b["verified"] is False
    assert b["glance"] == NOT_FOUND_GLANCE and "5 N-m" not in str(b)
    assert gen.calls == 2


def test_model_refusal_is_not_retried(client_app):
    client, app = client_app
    gen = app.state.pipeline.generator = ScriptedGenerator(Draft(answerable=False))
    b = ask(client, TORQUE).json()
    assert b["outcome"] == "not_found" and gen.calls == 1
    assert b["needs_clarification"] is False


def test_ambiguous_question_flags_needs_clarification(client_app):
    client, app = client_app
    gen = app.state.pipeline.generator = ScriptedGenerator(
        Draft(answerable=False, needs_clarification=True))
    b = ask(client, TORQUE).json()
    assert b["outcome"] == "not_found" and b["needs_clarification"] is True
    assert (b["glance"], b["citations"], b["verified"]) == (NOT_FOUND_GLANCE, [], False)
    assert gen.calls == 1
    app.state.pipeline.generator = ScriptedGenerator(GOOD)
    assert ask(client, TORQUE).json()["needs_clarification"] is False


def test_malformed_output_twice_is_llm_error(client_app):
    client, app = client_app
    app.state.pipeline.generator = ScriptedGenerator(ValueError("bad json"), ValueError("bad"))
    r = ask(client, TORQUE)
    assert r.status_code == 504 and r.json()["error"]["code"] == "llm_timeout"


def test_malformed_then_good_is_answered(client_app):
    client, app = client_app
    app.state.pipeline.generator = ScriptedGenerator(ValueError("bad json"), GOOD)
    assert ask(client, TORQUE).json()["outcome"] == "answered"


def test_glance_and_body_are_sanitized(client_app):
    client, app = client_app
    app.state.pipeline.generator = ScriptedGenerator(Draft(
        answerable=True, glance="Torque M5 to 4 N·m ✅", body="Torque to 4 N-m.",
        citations=GOOD.citations))
    b = ask(client, TORQUE).json()
    assert b["glance"].isascii() and b["outcome"] == "answered"


# --- caps fail loudly, never truncate ------------------------------------------------


def test_over_cap_glance_raises_not_truncated(client_app):
    client, app = client_app
    long_glance = "Torque M5 to 4 N-m " + "x" * 60
    app.state.pipeline.generator = ScriptedGenerator(Draft(
        answerable=True, glance=long_glance, body="Torque to 4 N-m.", citations=GOOD.citations))
    r = ask(client, TORQUE)
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal"
    assert long_glance[:40] not in r.text


def test_schema_caps():
    base = dict(trace_id="t", transcript="", intent="question", outcome="not_found", source="",
                citations=[], verified=False, latency_ms=Latency())
    AskResponse(glance="x" * 60, body="y" * 450, **base)
    with pytest.raises(ValidationError):
        AskResponse(glance="x" * 61, body="y", **base)
    with pytest.raises(ValidationError):
        AskResponse(glance="x", body="y" * 451, **base)
    with pytest.raises(ValidationError):
        Step(step_id="a", label="1", glance="x" * 61, body="")
    with pytest.raises(ValidationError):  # never an unverified answer
        AskResponse(glance="x", body="y", **(base | {"outcome": "answered"}))


# --- stage failures --------------------------------------------------------------------


def test_retrieval_failure_is_db_down(client_app):
    client, app = client_app

    class Down:
        async def retrieve(self, query, revision):
            raise DbDown("pool exhausted")

        async def steps_for(self, doc_id, revision):
            return []

    app.state.pipeline.retriever = Down()
    r = ask(client, TORQUE)
    assert r.status_code == 503 and r.json()["error"]["code"] == "db_down"


def test_part4_typed_error_code_is_respected(client_app):
    client, app = client_app

    class EmbeddingError(Exception):
        code = "llm_timeout"

    class Embeds:
        async def embed(self, q):
            raise EmbeddingError("embedding failed")

        async def retrieve(self, query, revision, q_embedding=None):
            raise AssertionError("unreachable")

        async def steps_for(self, doc_id, revision):
            return []

    app.state.pipeline.retriever = Embeds()
    r = ask(client, TORQUE)
    assert r.status_code == 504 and r.json()["error"]["code"] == "llm_timeout"


def test_gate_thresholds_from_config():
    client, app = make_client(not_found_min_sim=0.99, not_found_min_rrf=0.99)
    b = ask(client, TORQUE).json()
    assert b["outcome"] == "not_found" and app.state.pipeline.generator.calls == 0


def test_gate_needs_both_signals_weak(client_app):
    client, app = client_app

    class Strong:
        calls = 0

        async def retrieve(self, query, revision):
            from margin_relay.pipeline.mock import MOCK_CHUNKS
            return RetrievalResult(chunks=[MOCK_CHUNKS[1]], best_sim=0.1, best_rrf=0.9)

        async def steps_for(self, doc_id, revision):
            return []

    app.state.pipeline.retriever = Strong()
    assert ask(client, TORQUE).json()["outcome"] == "answered"  # rrf strong -> LLM runs


# --- events ------------------------------------------------------------------------------


def test_one_event_per_request_including_errors(client_app):
    client, app = client_app
    db = app.state.pipeline.db
    ask(client, TORQUE)
    ask(client, "boom")
    ask(client, "where is the good coffee")
    assert [e["outcome"] for e in db.events] == ["answered", "error", "not_found"]
    e = db.events[0]
    assert e["intent"] == "question" and e["doc_ids"] == ["SOP-114"] and e["transcript"] == TORQUE
    assert set(e["latency_ms"]) == {"stt", "embed", "retrieve", "generate", "verify", "total"}
    uuid.UUID(e["session_id"])
    assert len(e["trace_id"]) == 32


def test_event_write_failure_never_fails_request(client_app):
    client, app = client_app

    async def broken(**_):
        raise ConnectionError("tiger down")

    app.state.pipeline.db.write_event = broken
    assert ask(client, TORQUE).json()["outcome"] == "answered"


# --- deviation route ------------------------------------------------------------------


def test_deviation_route_contract_shape(client_app):
    client, app = client_app
    r = client.post("/v1/deviation", json={"session_id": sid(), "text": "gap too wide",
                                           "doc_id": "SOP-114", "step_id": "SOP-114:C:4.3"})
    assert r.status_code == 200 and r.json() == {"deviation_id": "DEV-0001", "notified": True}
    assert app.state.pipeline.db.deviations[-1]["step_id"] == "SOP-114:C:4.3"


def test_deviation_route_accepts_part2_context_shape(client_app):
    client, app = client_app
    r = client.post("/v1/deviation", json={"session_id": sid(), "text": "gap",
                                           "context": {"doc_id": "SOP-114", "step_id": None}})
    assert r.status_code == 200
    assert app.state.pipeline.db.deviations[-1]["doc_id"] == "SOP-114"


def test_deviation_is_stored_before_notifying(client_app):
    client, app = client_app
    db = app.state.pipeline.db
    seen_at_notify = []

    class Spy:
        async def notify(self, deviation_id, text):
            seen_at_notify.append([dict(r) for r in db.deviations])
            return True

    app.state.pipeline.notifier = Spy()
    r = client.post("/v1/deviation", json={"session_id": sid(), "text": "gap"})
    assert r.json()["notified"] is True
    assert seen_at_notify[0][-1]["notified"] is False  # durable row existed first
    assert db.deviations[-1]["notified"] is True  # then the flag was updated


def test_deviation_survives_notifier_failure(client_app):
    client, app = client_app

    class Fails:
        async def notify(self, deviation_id, text):
            raise ConnectionError("photon down")

    app.state.pipeline.notifier = Fails()
    r = client.post("/v1/deviation", json={"session_id": sid(), "text": "gap"})
    assert r.json()["notified"] is False
    assert app.state.pipeline.db.deviations[-1]["notified"] is False
    b = ask(client, "log a deviation screw stripped").json()
    assert b["outcome"] == "logged" and "alert failed" in b["body"]


def test_deviation_db_down(client_app):
    client, app = client_app

    async def down():
        raise ConnectionError

    app.state.pipeline.db.next_deviation_id = down
    r = client.post("/v1/deviation", json={"session_id": sid(), "text": "gap"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "db_down"
    assert ask(client, "log deviation gap").status_code == 503


# --- procedures + ingest ----------------------------------------------------------------


def test_procedures(client):
    docs = client.get("/v1/procedures").json()
    assert {"doc_id": "SOP-114", "title": "Mounting Bracket Assembly", "revision": "C",
            "status": "effective"} in docs
    steps = client.get("/v1/procedures/SOP-114/steps").json()
    assert [s["label"] for s in steps] == [f"4.{i}" for i in range(1, 8)]
    assert client.get("/v1/procedures/SOP-114/steps?revision=Z").json() == []


def test_ingest_requires_admin_token():
    client, _ = make_client()
    assert client.post("/v1/ingest").status_code == 403
    client, _ = make_client(admin_token="s3cret")
    assert client.post("/v1/ingest").status_code == 401
    assert client.post("/v1/ingest", headers={"authorization": "Bearer nope"}).status_code == 401
    r = client.post("/v1/ingest", headers={"authorization": "Bearer s3cret"})
    assert r.status_code == 200 and r.json()["mock"] is True


def test_mock_generator_is_counted():
    assert MockGenerator().calls == 0
