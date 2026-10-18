"""The shipped demo bank: corpus/ (Ember & Oak coffee SOPs) and eval/qa.jsonl.

Checks the bank is self-consistent before anything is seeded: every procedural step
fits the lens, and every answerable eval question's expected values are verbatim in
the section it cites. Hashes retain the original baseline after duplicate root files were removed."""
from collections import Counter
import json
import hashlib
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
    # Baseline from the supplied originals at 3457a46, before main removed duplicate files.
    hashes = {
        201: "f8866766a5e30c49d8d3a338afe6b46ed2b20586f86313c1ccbe3b3ae4468eca",
        202: "53023116533016ab5a3c12f2450faea737f3ff7d15ed483b85a52d0a95c94a9d",
        210: "ca67591c74be9b84f2fd408ddc8080cf88c92443243af29ca0149aeb8898d3d2",
        220: "2df1d11253d3bb6332b9f72c1fb70011655fa7cd5c37beb4b9eaec4bde037ca3",
        230: "c354d83ec7dc16806a12c82a8d372081c80e10cf7a03d0f9465f9ba4406ffabe",
    }
    for n, digest in hashes.items():
        shipped = (ROOT / f"corpus/SOP-{n}-C.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        assert hashlib.sha256(shipped.replace("synthetic: true\n", "", 1).encode()).hexdigest() == digest


def test_eval_bank_answers_are_verbatim_in_the_cited_sections():
    cases = evaluation.load_cases(ROOT / "eval/qa.jsonl")
    assert Counter(c["category"] for c in cases if not c["id"].startswith("v3-")) == {
        "answerable": 36, "off-domain": 4, "near-miss": 3, "ambiguous": 2}
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
    # Preserve the original 45 questions and expected results without a duplicate root qa.jsonl.
    cases = evaluation.load_cases(ROOT / "eval/qa.jsonl")
    fields = ["q", "expect", "needs_clarification", "doc_id", "section", "must_contain"]
    source = [json.loads(line) for line in (ROOT / "eval/qa.jsonl").read_text(encoding="utf-8").splitlines() if line]
    canonical = [{k: c[k] for k in fields if k in c} for c in source[:45]]
    assert hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest() == \
        "904bfb9028bdb4c27b027d53db2ad1c967bdb85a0fae6257ad7d795fd5cccf0a"
    assert len([c for c in cases if c["id"].startswith("v3-")]) == 18


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
