"""Offline v3 contract and worker-loop regressions; no provider or database calls."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from google.genai.errors import APIError
from pydantic import ValidationError

from db.seed import load_corpus
from specs_relay.config import Settings
from specs_relay.main import Pipeline, _adapt_intent, create_app
from specs_relay.pipeline import mock
from specs_relay.pipeline.intent import classify_intent, deviation_text, parse_command
from specs_relay.pipeline.retrieve import EmbeddingError, GeminiEmbedder
from specs_relay.pipeline.sanitize import sanitize
from specs_relay.pipeline.verify import verify
from specs_relay.routes.ask import _clarify, _walkthrough_document
from specs_relay.schemas import Chunk, Clarify, Draft, RetrievalResult, Scope, Step, Walkthrough
from specs_relay.walkthrough import step_from_chunk

DOCS, ROWS = load_corpus(Path(__file__).resolve().parents[2] / "corpus")
TITLES = {(d["doc_id"], d["revision"]): d["title"] for d in DOCS}
BY_ID = {r["chunk_id"]: r for r in ROWS}


def chunk(doc, section):
    return Chunk(**BY_ID[f"{doc}:C:{section}"], title=TITLES[doc, "C"])


class Retriever:
    def __init__(self, chunks):
        self.chunks, self.queries = chunks, []

    async def retrieve(self, query, revision):
        self.queries.append(query)
        return RetrievalResult(chunks=self.chunks, best_sim=0.9, best_rrf=0.04)

    async def steps_for(self, doc, revision):
        return [step_from_chunk(r) for r in ROWS if r["doc_id"] == doc and r["is_step"]
                and (revision is None or r["revision"] == revision)]


class Generator:
    def __init__(self, *drafts):
        self.drafts, self.requests = list(drafts), []

    async def generate(self, query, chunks, feedback=None):
        self.requests.append((query, chunks))
        return self.drafts.pop(0)


def pipeline(retriever, generator):
    return Pipeline(transcriber=mock.MockTranscriber(), classify=_adapt_intent(classify_intent, deviation_text),
                    retriever=retriever, generator=generator, verify=verify, sanitize=sanitize,
                    notifier=mock.MockNotifier(), db=mock.MockDB(), real_db=False, parse_command=parse_command)


def client(p):
    return TestClient(create_app(Settings(_env_file=None, mock_mode=True, sentry_dsn_relay=""), p))


def ask(c, text, sid=None, **kwargs):
    r = c.post("/v1/ask", json={"session_id": str(sid or uuid4()), "text": text, **kwargs})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("options", [["Latte"], ["Latte"] * 2, ["A", "B", "C", "D"], ["x" * 25, "B"]])
def test_clarify_options_reject_missing_duplicate_or_oversize_choices(options):
    with pytest.raises(ValidationError):
        Clarify(prompt="Which drink?", options=options)


@pytest.mark.parametrize("start,index,end,total", [(0, 0, 2, 1), (1, 0, 2, 2), (1, 1, 1, 2), (0, 2, 2, 2)])
def test_invalid_walkthrough_scope_is_rejected(start, index, end, total):
    steps = [Step(step_id=f"X:C:{i}", label=str(i), glance="Step", body="Do it.") for i in range(total)]
    with pytest.raises(ValidationError):
        Walkthrough(doc_id="X", revision="C", title="T", total=total, index=index, steps=steps,
                    scope=Scope(start=start, end=end))


def test_clarify_uses_only_distinct_retrieved_headings_within_caps():
    chunks = [chunk("SOP-230", "2.1").model_copy(update={"heading": name})
              for name in ("Latte", "Cappuccino", "Latte", "x" * 25)]
    assert _clarify(chunks, sanitize).options == ["Latte", "Cappuccino"]
    assert _clarify(chunks[:1], sanitize) is None
    other = chunk("SOP-220", "4.4").model_copy(update={"title": "Espresso standards"})
    assert _clarify([chunks[0], other], sanitize).options == ["Drink Recipes", "Espresso standards"]


@pytest.mark.parametrize("reply,combine", [("cappuccino", True), ("Cappuccino", True),
    ("how do I clean the steam wand after the shift", False)])
def test_clarify_reply_resolves_in_the_same_session(reply, combine):
    latte = chunk("SOP-230", "2.1").model_copy(update={"heading": "Latte"})
    cap = chunk("SOP-230", "3.1").model_copy(update={"heading": "Cappuccino"})
    ret = Retriever([latte, cap])
    gen = Generator(Draft(answerable=False, needs_clarification=True), Draft(answerable=False))
    sid = uuid4()
    with client(pipeline(ret, gen)) as c:
        first = ask(c, "How many pumps of syrup?", sid)
        assert first["clarify"]["options"] == ["Latte", "Cappuccino"]
        assert first["verified"] is False and first["citations"] == []
        ask(c, reply, sid)
    assert ret.queries[-1] == ("How many pumps of syrup? " + reply if combine else reply)


def test_clarify_does_not_leak_to_another_session():
    ret = Retriever([chunk("SOP-230", "2.1"), chunk("SOP-230", "3.4")])
    gen = Generator(Draft(answerable=False, needs_clarification=True), Draft(answerable=False))
    with client(pipeline(ret, gen)) as c:
        assert ask(c, "How many pumps?")["clarify"] is not None
        ask(c, "cappuccino")
    assert ret.queries[-1] == "cappuccino"


def test_follow_up_keeps_current_source_first_then_previous_citations():
    prior = chunk("SOP-220", "4.2")
    draft = Draft(answerable=True, glance="Extra hot: 160 degF", citations=[
        {"chunk_id": prior.chunk_id, "quote": prior.text}])
    ret, gen = Retriever([prior]), Generator(draft, draft)
    sid = uuid4()
    with client(pipeline(ret, gen)) as c:
        assert ask(c, "How hot should the milk be?", sid)["outcome"] == "answered"
        ret.chunks = [chunk("SOP-230", "1.3")]
        out = ask(c, "What about extra hot?", sid,
                  context={"doc_id": "SOP-230", "step_id": "SOP-230:C:3.3"})
    assert out["verified"] is True
    query, chunks = gen.requests[-1]
    assert chunks[0].chunk_id == "SOP-230:C:3.3"
    assert chunks[1].chunk_id == prior.chunk_id and chunks[1].text == prior.text
    assert len(chunks) <= 6 and "Previous question" in query


@pytest.mark.parametrize("query,doc,section", [
    ("show me how to pull a good espresso shot", "SOP-220", "3.1"),
    ("pull up the espresso standards", "SOP-220", "3.1"),
    ("walk me through making a cappuccino", "SOP-230", "3.2"),
    ("take me through closing out the till", "SOP-202", "7.1"),
    ("guide me through kitchen opening", "SOP-210", "3.1"),
])
def test_document_choice_and_scoped_section(query, doc, section):
    hit = chunk(doc, section)
    wrong = chunk("SOP-230", "3.2") if doc != "SOP-230" else chunk("SOP-220", "4.6")
    ret, gen = Retriever([wrong, hit]), Generator()
    assert _walkthrough_document(query, ret.chunks).doc_id == doc
    with client(pipeline(ret, gen)) as c:
        out = ask(c, query)
    walk = out["walkthrough"]
    assert walk["doc_id"] == doc and walk["steps"][walk["index"]]["label"] == section
    scoped = walk["steps"][walk["scope"]["start"]:walk["scope"]["end"]]
    assert all(s["label"].split(".")[0] == section.split(".")[0] for s in scoped)
    if doc == "SOP-230":
        assert [s["label"] for s in scoped] == ["3.2", "3.3", "3.4"]
    assert gen.requests == []


def test_authored_paraphrase_is_never_used_as_a_source_quote():
    row = {**BY_ID["SOP-220:C:3.1"], "body": "An authored paraphrase.", "glance": "Purge"}
    class Authored(Retriever):
        async def steps_for(self, doc, revision):
            return [step_from_chunk(row)]
    with client(pipeline(Authored([Chunk(**row)]), Generator())) as c:
        out = ask(c, "walk me through espresso shot")
    assert out["outcome"] == "answered"
    assert out["citations"][0]["quote"] == row["text"]
    assert "authored paraphrase" not in out["citations"][0]["quote"]


def test_picture_question_returns_a_cited_reference_without_generation():
    ret, gen = Retriever([chunk("SOP-220", "4.4")]), Generator()
    with client(pipeline(ret, gen)) as c:
        out = ask(c, "What does the steam wand look like?")
        command = ask(c, "show me the picture")
    assert out["outcome"] == "answered" and out["verified"]
    assert out["graphic_id"] == "milk-steaming" and out["citations"]
    assert command["outcome"] == "command" and command["command"] == "diagram"
    assert gen.requests == []


def test_picture_without_a_matching_retrieved_reference_refuses():
    with client(pipeline(Retriever([chunk("SOP-230", "1.3")]), Generator())) as c:
        assert ask(c, "picture of the steam wand")["outcome"] == "not_found"


@pytest.mark.parametrize("codes,timeout,calls,success", [([429, None], 1, 2, True),
    ([503, None], 1, 2, True), ([429, 429], 1, 2, False), ([400, None], 1, 1, False),
    ([429, None], 0.1, 1, False)])
def test_embedding_retry_is_bounded(codes, timeout, calls, success):
    requests = []
    async def embed_content(**kwargs):
        requests.append(kwargs)
        code = codes.pop(0)
        if code:
            raise APIError(code, {"error": {"message": "api"}})
        return NS(embeddings=[NS(values=[3.0, 4.0])])
    embedder = GeminiEmbedder(NS(aio=NS(models=NS(embed_content=embed_content))), "embedding-001", 2, timeout=timeout)
    if success:
        assert asyncio.run(embedder.embed_query("q")) == [0.6, 0.8]
    else:
        with pytest.raises(EmbeddingError):
            asyncio.run(embedder.embed_query("q"))
    assert len(requests) == calls


@pytest.mark.parametrize("case", [json.loads(line) for line in (
    Path(__file__).parent / "fixtures/verify-false-negatives.jsonl").read_text(encoding="utf-8").splitlines()])
def test_temperature_quotes_keep_inner_quotes_and_units(case):
    source = chunk("SOP-220", "4.2").model_copy(update={"text": case["text"]})
    draft = Draft(answerable=True, glance=case["glance"], body=case["body"],
                  citations=[{"chunk_id": source.chunk_id, "quote": case["quote"]}])
    assert verify(draft, [source]).ok
    assert not verify(draft.model_copy(update={"glance": "Use 999 degF"}), [source]).ok


@pytest.mark.parametrize("answer", ["Use 12", "Use 12 ppm", "Use 12 pumps"])
def test_coffee_units_cannot_be_dropped_or_substituted(answer):
    source = chunk("SOP-220", "4.5").model_copy(update={"text": "Use 12 oz."})
    draft = Draft(answerable=True, glance=answer, citations=[{"chunk_id": source.chunk_id, "quote": source.text}])
    assert not verify(draft, [source]).ok


def test_mock_clarify_reply_and_scoped_walkthrough():
    from specs_relay.main import build_pipeline
    settings = Settings(_env_file=None, mock_mode=True, sentry_dsn_relay="")
    with TestClient(create_app(settings, build_pipeline(settings))) as c:
        sid = uuid4()
        assert ask(c, "How many pumps of syrup?", sid)["clarify"] is not None
        reply = ask(c, "latte", sid)
        assert reply["outcome"] == "answered" and "pumps" in reply["body"]
        walk = ask(c, "walk me through making a cappuccino")["walkthrough"]
        assert walk["scope"] == {"start": 0, "end": 3}
