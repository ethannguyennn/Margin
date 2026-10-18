"""The shipped demo bank: corpus/ (Ember & Oak coffee SOPs) and eval/qa.jsonl.

Checks the bank is self-consistent before anything is seeded: every procedural step
fits the lens, and every answerable eval question's expected values are verbatim in
the section it cites. The originals the team supplied are at the repo root."""
from collections import Counter
import json
from pathlib import Path

import pytest

from db import seed
from eval import run_eval as evaluation
from specs_relay.walkthrough import step_from_chunk

ROOT = Path(__file__).resolve().parents[2]


def test_corpus_is_the_five_coffee_sops_with_marked_steps():
    documents, chunks = seed.load_corpus()
    assert {(d["doc_id"], d["revision"], d["status"]) for d in documents} == {
        (f"SOP-{n}", "C", "effective") for n in (201, 202, 210, 220, 230)}
    steps = [c for c in chunks if c["is_step"]]
    assert (len(chunks), len(steps)) == (134, 72)
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


def test_corpus_copies_match_the_supplied_originals_except_the_synthetic_flag():
    for n in (201, 202, 210, 220, 230):
        original = (ROOT / f"SOP-{n}.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        shipped = (ROOT / f"corpus/SOP-{n}-C.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        assert shipped.replace("synthetic: true\n", "", 1) == original


def test_eval_bank_answers_are_verbatim_in_the_cited_sections():
    cases = evaluation.load_cases(ROOT / "eval/qa.jsonl")
    assert Counter(c["category"] for c in cases) == {
        "answerable": 36, "off-domain": 4, "near-miss": 3, "ambiguous": 2}
    index = evaluation.citation_index()
    for case in cases:
        if case["expect"] != "answered":
            continue
        chunk = index[f"{case['doc_id']}:{case['revision']}:{case['section']}"]
        missing = [m for m in case["must_contain"] if not evaluation.contains(chunk["text"], m)]
        assert not missing, f"{case['id']} {case['q']!r}: {missing} not in section {case['section']}"


def test_eval_bank_keeps_the_supplied_questions():
    supplied = [json.loads(line) for line in (ROOT / "qa.jsonl").read_text(encoding="utf-8").splitlines() if line]
    cases = evaluation.load_cases(ROOT / "eval/qa.jsonl")
    assert [c["q"] for c in cases] == [s["q"] for s in supplied]
    for case, s in zip(cases, supplied):
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
