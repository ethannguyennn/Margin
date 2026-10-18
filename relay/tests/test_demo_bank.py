"""The shipped demo bank: corpus/ (Ember & Oak coffee SOPs) and eval/qa.jsonl.

Checks the bank is self-consistent before anything is seeded: every procedural step
fits the lens, and every answerable eval question's expected values are verbatim in
the section it cites. The team's supplied question list is eval/supplied-qa.jsonl."""
from collections import Counter
import json
from pathlib import Path

import pytest

from db import seed
from eval import run_eval as evaluation
from specs_relay.walkthrough import step_from_chunk

ROOT = Path(__file__).resolve().parents[2]


SOPS = (201, 202, 210, 220, 230, 231, 240, 250, 260, 270, 280, 290, 300)


def test_corpus_is_the_thirteen_coffee_sops_with_marked_steps():
    documents, chunks = seed.load_corpus()
    assert {(d["doc_id"], d["revision"], d["status"]) for d in documents} == {
        (f"SOP-{n}", "C", "effective") for n in SOPS}
    steps = [c for c in chunks if c["is_step"]]
    assert (len(chunks), len(steps)) == (353, 149)
    assert not any(seed.STEP_MARKER in c["text"] for c in chunks), "the marker is stripped"
    for doc in documents:
        orders = [c["step_order"] for c in steps if c["doc_id"] == doc["doc_id"]]
        assert orders == list(range(1, len(orders) + 1))
    by_id = {c["chunk_id"]: c for c in chunks}
    assert by_id["SOP-201:C:2.2"]["is_step"] and by_id["SOP-201:C:2.2"]["text"].startswith("Count the cash drawer")
    assert not by_id["SOP-201:C:4.2"]["is_step"], "a price table is reference, not a step"


def test_every_step_fits_the_lens():
    _, chunks = seed.load_corpus()
    for chunk in chunks:
        if chunk["is_step"]:
            step_from_chunk(chunk)  # raises past the 449-character body cap


def test_eval_bank_answers_are_verbatim_in_the_cited_sections():
    cases = evaluation.load_cases(ROOT / "eval/qa.jsonl")
    assert Counter(c["category"] for c in cases if not c["id"].startswith("v3-")) == {
        "answerable": 107, "off-domain": 4, "near-miss": 7, "ambiguous": 3}
    index = evaluation.citation_index()
    turns = [turn for case in cases for turn in [case, *case.get("turns", [])]]
    for case in turns:
        if case["expect"] != "answered":
            continue
        chunk = index[f"{case['doc_id']}:{case['revision']}:{case['section']}"]
        text = chunk["text"]
        if case.get("graphic_id"):
            from specs_relay.illustrations import available_graphics
            graphic = next(g for g in available_graphics([chunk]) if g["id"] == case["graphic_id"])
            text = graphic["title"]
        missing = [m for m in case.get("must_contain", []) if not evaluation.contains(text, m)]
        assert not missing, f"{case['id']} {case['q']!r}: {missing} not in section {case['section']}"


def test_eval_bank_keeps_the_supplied_questions():
    supplied = [json.loads(line) for line in (ROOT / "eval/supplied-qa.jsonl").read_text(encoding="utf-8").splitlines() if line]
    cases = evaluation.load_cases(ROOT / "eval/qa.jsonl")
    assert len([c for c in cases if c["id"].startswith("v3-")]) == 18
    by_q = {c["q"]: c for c in cases}
    assert all(s["q"] in by_q for s in supplied)
    for s in supplied:
        case = by_q[s["q"]]
        if s["expect"] == "clarify":  # the relay reports ambiguity as not_found + needs_clarification
            assert (case["expect"], case.get("needs_clarification")) == ("not_found", True)
        else:
            assert case["expect"] == s["expect"]
            assert [case.get(k) for k in ("doc_id", "section")] == [s["doc_id"], s["section"]]
            assert case.get("must_contain", []) == s["must_contain"]


@pytest.mark.parametrize("body, error", [
    ("### 1.1 Mixed\n<!-- step -->\nDo this.\n\n### 1.2 Numbered\n1. Do that.\n", "one way"),
    ("### 1.1 Empty\n<!-- step -->\n\n### 1.2 Next\n<!-- step -->\nDo that.\n", "no text"),
])
def test_step_markers_are_validated(tmp_path, body, error):
    path = tmp_path / "SOP-999-A.md"
    path.write_text("---\ndoc_id: SOP-999\ntitle: T\nrevision: A\nstatus: effective\n"
                    "effective_date: 2026-03-01\nsynthetic: true\n---\n" + body, encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        seed.parse_document(path)
