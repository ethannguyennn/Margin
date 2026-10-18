"""M4 acceptance through Part 3's real /v1/ask route: Part 4's real intent,
verify and sanitize, with a fake retriever (fixed scores) and a scripted
generator (call counter). No network, no database."""

import base64
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from specs_relay.config import Settings
from specs_relay.main import Pipeline, _adapt_intent, create_app
from specs_relay.pipeline import mock
from specs_relay.pipeline.intent import classify_intent, deviation_text
from specs_relay.pipeline.sanitize import sanitize
from specs_relay.pipeline.transcribe import MockTranscriber
from specs_relay.pipeline.verify import verify
from specs_relay.schemas import Draft, RetrievalResult

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


# --- a follow-up question knows the step the worker is on ---------------------------
RINSE = "Rinse the wetted path with purified water at 60°C for 5 min."


class StepRetriever(FakeRetriever):
    async def steps_for(self, doc_id, revision):
        from specs_relay.schemas import Step
        return [Step(step_id="SOP-120:B:3.1", label="3.1", glance="Rinse", body=RINSE, text=RINSE)] if doc_id == "SOP-120" else []


class RecordingGenerator(ScriptedGenerator):
    async def generate(self, query, chunks, feedback=None):
        self.query, self.chunks = query, chunks
        return await super().generate(query, chunks, feedback)


def step_client(gen):
    c = client_for(gen)
    c.app.state.pipeline.retriever = StepRetriever()
    return c


HERE = {"doc_id": "SOP-120", "step_id": "SOP-120:B:3.1"}
FIVE_MIN = {"answerable": True, "needs_clarification": False, "glance": "Rinse for 5 min", "body": "",
            "citations": [{"chunk_id": "SOP-120:B:3.1", "quote": RINSE}], "graphic_id": None}


def test_follow_up_resolves_against_the_current_step():
    gen = RecordingGenerator(FIVE_MIN)
    with step_client(gen) as c:
        # Retrieval alone is below both gates ("that" names nothing); the step context answers it.
        out = ask(c, "how long do I do that for", context=HERE)
    assert out["outcome"] == "answered" and out["verified"] is True, out
    assert out["source"] == "SOP-120 Sec 3.1 rev B"
    assert gen.chunks[0].chunk_id == "SOP-120:B:3.1" and len(gen.chunks) <= 6
    assert "SOP-120:B:3.1" in gen.query and gen.query.startswith("how long do I do that for")


def test_unknown_step_context_falls_back_to_plain_retrieval():
    gen = RecordingGenerator(FIVE_MIN)
    with step_client(gen) as c:
        out = ask(c, "how long do I do that for", context={"doc_id": "SOP-120", "step_id": "SOP-120:B:9.9"})
    assert out["outcome"] == "not_found" and gen.calls == 0


# --- a walkthrough starts at the section the worker asked for -----------------------
class TillRetriever:
    async def retrieve(self, query, revision):
        from specs_relay.schemas import Chunk
        hits = [Chunk(chunk_id=f"SOP-202:C:{s}", doc_id="SOP-202", revision="C", section=s, text="t", is_step=True)
                for s in ("7.2", "2.3", "7.1")]
        return RetrievalResult(chunks=hits, best_sim=0.79, best_rrf=0.032)

    async def steps_for(self, doc_id, revision):
        from specs_relay.schemas import Step
        return [Step(step_id=f"SOP-202:C:{s}", label=s, glance=f"Step {s}", body=f"Do {s}.", text=f"Do {s}.")
                for s in ("2.3", "5.1", "7.1", "7.2", "7.3")]


def test_walkthrough_starts_at_the_first_step_of_the_asked_section():
    c = client_for(ScriptedGenerator(GOOD))
    c.app.state.pipeline.retriever = TillRetriever()
    with c:
        out = ask(c, "take me through closing out the till")
    w = out["walkthrough"]
    assert out["intent"] == "walkthrough" and (w["total"], w["index"]) == (5, 2), out
    assert w["steps"][w["index"]]["label"] == "7.1" and out["source"] == "SOP-202 Sec 7.1 rev C"


def test_uncited_graphic_is_dropped_not_the_answer():
    gen = ScriptedGenerator({**GOOD, "graphic_id": "allergen-binder"})
    with client_for(gen) as c:
        out = ask(c, M5)
    assert out["outcome"] == "answered" and out["verified"] is True, out
    assert out["graphic_id"] is None and gen.calls == 1


# --- v3 trust fix (4.7): walkthrough citations quote the stored source, never the body ---
SOURCE = "Count the drawer twice. Record the total on form T-7."
PARAPHRASE = "Count the money and write it down."


class AuthoredRetriever(TillRetriever):
    async def steps_for(self, doc_id, revision):
        from specs_relay.schemas import Step
        return [Step(step_id="SOP-202:C:7.1", label="7.1", glance="Count the drawer", body=PARAPHRASE,
                     text=SOURCE),
                Step(step_id="SOP-202:C:7.2", label="7.2", glance="Lock the till", body="Lock it.")]  # no source


def test_a_paraphrased_body_never_appears_as_a_citation_quote():
    c = client_for(ScriptedGenerator(GOOD))
    c.app.state.pipeline.retriever = AuthoredRetriever()
    with c:
        out = ask(c, "take me through closing out the till")
    quotes = [x["quote"] for x in out["citations"]]
    assert out["verified"] is True and quotes == [SOURCE]   # 7.2 has no source text: not cited
    assert PARAPHRASE not in quotes and "Lock it." not in quotes


def test_step_context_without_source_text_is_not_used():
    class NoText(StepRetriever):
        async def steps_for(self, doc_id, revision):
            from specs_relay.schemas import Step
            return [Step(step_id="SOP-120:B:3.1", label="3.1", glance="Rinse", body=RINSE)]
    gen = RecordingGenerator(FIVE_MIN)
    c = client_for(gen)
    c.app.state.pipeline.retriever = NoText()
    with c:
        out = ask(c, "how long do I do that for", context=HERE)
    assert out["outcome"] == "not_found" and gen.calls == 0   # no paraphrase to quote from
