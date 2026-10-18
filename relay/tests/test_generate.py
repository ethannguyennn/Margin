"""Grounded generation + the question path, against six hardcoded chunks.

No network: the Gemini client is a fake that records requests. The live call
is exercised by tests/test_live_gemini.py when a key is configured.
"""

import asyncio
import json
from types import SimpleNamespace as NS

import pytest

schemas = pytest.importorskip("margin_relay.schemas")

from margin_relay.pipeline.generate import (  # noqa: E402
    NOT_FOUND_GLANCE,
    RESPONSE_SCHEMA,
    SYSTEM_PROMPT,
    GeminiGenerator,
    GenerationError,
    GenerationTimeout,
    answer_question,
    build_prompt,
)


def C(cid, text, heading=None):
    doc, rev, sec = cid.split(":")
    return schemas.Chunk(chunk_id=cid, doc_id=doc, revision=rev, section=sec, text=text, heading=heading)


CHUNKS = [
    C("SOP-114:C:4.2", "Torque all four M5 bracket screws to 4 N-m in a star pattern using a calibrated "
      "torque wrench (see SOP-131).", "Fastening"),
    C("SOP-114:C:4.1", "Seat the bracket on the two dowel pins and hand-start all four M5 screws.", "Preparation"),
    C("SOP-114:C:4.3", "Apply a torque stripe across each screw head and bracket.", "Witness marking"),
    C("SOP-131:B:3", "Check the torque wrench against the bench analyzer at 4 N-m; reject if the reading "
      "deviates by more than 4 %.", "Daily check"),
    C("SOP-120:B:3.1", "Rinse the wetted path with purified water at 60°C for 5 min.", "Rinse"),
    C("SOP-101:A:2.3", "Reject any carton with a tilt indicator showing red.", "Carton check"),
]
Q42 = "Torque all four M5 bracket screws to 4 N-m in a star pattern"

GOOD = {
    "answerable": True,
    "needs_clarification": False,
    "glance": "Step 4.2: torque M5 to 4 N-m",
    "body": "Torque all four M5 bracket screws to 4 N-m in a star pattern.",
    "citations": [{"chunk_id": "SOP-114:C:4.2", "quote": Q42}],
}
HALLUCINATED = {**GOOD, "glance": "Torque M5 to 5 N-m", "body": "Torque all four M5 bracket screws to 5 N-m."}


def retrieval(best_sim=0.82, best_rrf=0.032, chunks=CHUNKS):
    return schemas.RetrievalResult(chunks=chunks, best_sim=best_sim, best_rrf=best_rrf)


class FakeRetriever:
    def __init__(self, result):
        self.result, self.calls = result, 0

    async def retrieve(self, query, revision):
        self.calls += 1
        return self.result


class ScriptedGenerator:
    """Returns the scripted drafts in order and counts calls."""

    def __init__(self, *drafts):
        self.drafts, self.calls, self.feedback = list(drafts), 0, []

    async def generate(self, query, chunks, feedback=None):
        self.calls += 1
        self.feedback.append(feedback)
        d = self.drafts.pop(0)
        if isinstance(d, Exception):
            raise d
        return schemas.Draft.model_validate(d)


def ask(gen, result=None, **kw):
    kw.setdefault("min_sim", 0.60)
    kw.setdefault("min_rrf", 0.030)
    return asyncio.run(answer_question("how tight is the m5 on the mounting bracket",
                                       FakeRetriever(result or retrieval()), gen, revision=None, **kw))


# --- acceptance: the trust layer ------------------------------------------------

def test_off_document_question_is_refused_without_an_llm_call():
    gen = ScriptedGenerator(GOOD)
    out = ask(gen, retrieval(best_sim=0.31, best_rrf=0.0164))
    assert out.outcome == "not_found"
    assert gen.calls == 0
    assert out.llm_calls == 0
    assert out.glance == NOT_FOUND_GLANCE
    assert out.verified is False and out.citations == []


def test_forced_hallucination_is_caught_and_degrades_to_not_found():
    gen = ScriptedGenerator(HALLUCINATED, HALLUCINATED)
    out = ask(gen)
    assert out.outcome == "not_found"
    assert out.verified is False
    assert gen.calls == 2                      # retried exactly once
    assert "5 N-m" not in out.glance + out.body
    assert all(r.startswith("unsupported_number") for r in out.reasons)


def test_retry_receives_the_failure_reason_and_can_recover():
    gen = ScriptedGenerator(HALLUCINATED, GOOD)
    out = ask(gen)
    assert out.outcome == "answered" and out.verified is True
    assert gen.feedback[0] is None
    assert gen.feedback[1].startswith("unsupported_number")


def test_answer_carries_renderable_citation():
    out = ask(ScriptedGenerator(GOOD))
    assert out.outcome == "answered"
    assert out.source == "SOP-114 Sec 4.2 rev C"
    c = out.citations[0]
    assert (c.chunk_id, c.doc_id, c.revision, c.section) == ("SOP-114:C:4.2", "SOP-114", "C", "4.2")
    assert out.glance == "Step 4.2: torque M5 to 4 N-m"


def test_answer_text_is_sanitized():
    d = {**GOOD, "glance": "Torque M5 to 4 N·m ✅", "body": "Torque M5 to 4 N·m.",
         "citations": [{"chunk_id": "SOP-114:C:4.2", "quote": Q42}]}
    out = ask(ScriptedGenerator(d))
    assert out.glance == "Torque M5 to 4 N-m"
    assert out.glance.isascii() and out.body.isascii()


def test_model_refusal_is_not_retried():
    gen = ScriptedGenerator({"answerable": False, "needs_clarification": False, "glance": "", "body": "",
                             "citations": []})
    out = ask(gen)
    assert out.outcome == "not_found" and gen.calls == 1


def test_ambiguity_becomes_clarify():
    gen = ScriptedGenerator({"answerable": False, "needs_clarification": True, "glance": "", "body": "",
                             "citations": []})
    out = ask(gen)
    assert out.outcome == "clarify" and out.verified is False and out.citations == []


def test_malformed_output_is_retried_then_refused():
    gen = ScriptedGenerator(GenerationError("bad json"), GenerationError("bad json"))
    out = ask(gen)
    assert out.outcome == "not_found" and gen.calls == 2


def test_timeout_propagates_for_llm_timeout():
    with pytest.raises(GenerationTimeout):
        ask(ScriptedGenerator(GenerationTimeout("slow")))


def test_gate_passes_when_only_one_signal_is_strong():
    assert ask(ScriptedGenerator(GOOD), retrieval(best_sim=0.85, best_rrf=0.0164)).outcome == "answered"
    assert ask(ScriptedGenerator(GOOD), retrieval(best_sim=0.30, best_rrf=0.0325)).outcome == "answered"


def test_empty_retrieval_is_refused():
    gen = ScriptedGenerator(GOOD)
    assert ask(gen, retrieval(best_sim=0.0, best_rrf=0.0, chunks=[])).outcome == "not_found"
    assert gen.calls == 0


# --- GeminiGenerator against a fake client ---------------------------------------

class FakeModels:
    def __init__(self, text=None, delay=0.0):
        self.text, self.delay, self.requests = text, delay, []

    async def generate_content(self, *, model, contents, config):
        self.requests.append(NS(model=model, contents=contents, config=config))
        await asyncio.sleep(self.delay)
        return NS(text=self.text)


def client(**kw):
    return NS(aio=NS(models=FakeModels(**kw)))


def test_generator_requests_structured_low_temperature_output():
    cl = client(text=json.dumps(GOOD))
    draft = asyncio.run(GeminiGenerator(cl, "model-from-config").generate("how tight is the m5", CHUNKS))
    assert isinstance(draft, schemas.Draft)
    assert draft.citations[0].chunk_id == "SOP-114:C:4.2"
    req = cl.aio.models.requests[0]
    assert req.model == "model-from-config"
    assert req.config.response_mime_type == "application/json"
    assert req.config.response_json_schema == RESPONSE_SCHEMA
    assert req.config.temperature <= 0.2
    assert req.config.system_instruction == SYSTEM_PROMPT
    for c in CHUNKS:
        assert f"[chunk_id: {c.chunk_id}]" in req.contents


def test_generator_output_validates_against_draft():
    assert set(RESPONSE_SCHEMA["required"]) <= set(schemas.Draft.model_fields)


def test_generator_uses_the_configured_route_timeout_budget():
    settings = NS(gemini_api_key='', gemini_model_generate='model-from-config', generate_timeout_s=12.5)
    assert GeminiGenerator.from_settings(settings, client=client()).timeout == 12.5


def test_generator_malformed_json_raises_typed_error():
    with pytest.raises(GenerationError):
        asyncio.run(GeminiGenerator(client(text="Torque it to 4 N-m."), "m").generate("q", CHUNKS))


def test_generator_timeout_raises_typed_error():
    gen = GeminiGenerator(client(text=json.dumps(GOOD), delay=0.5), "m", timeout=0.01)
    with pytest.raises(GenerationTimeout) as e:
        asyncio.run(gen.generate("q", CHUNKS))
    assert e.value.code == "llm_timeout"


def test_system_prompt_keeps_every_rule():
    for needle in ["ONLY the provided CONTEXT", "answerable=false. Never guess", "verbatim quote",
                   "<= 60 characters", "<= 450 characters", "Never convert units",
                   "needs_clarification=true"]:
        assert needle in SYSTEM_PROMPT


def test_retry_prompt_contains_feedback():
    p = build_prompt("q", CHUNKS[:1], feedback="unsupported_number: glance states '5 nm'")
    assert "REJECTED" in p and "5 nm" in p
