import json

import httpx
import pytest

from part5_support import ROOT
from eval import run_eval as evaluation


def fixture_answer(case, index):
    """Answer-key fixture, not a retrieval/generation implementation."""
    if case["expect"] == "not_found":
        return {"trace_id": "fixture", "outcome": "not_found", "verified": False,
                "citations": [], "needs_clarification": case.get("needs_clarification", False)}
    chunk = index[f"{case['doc_id']}:{case['revision']}:{case['section']}"]
    return {"trace_id": "fixture", "outcome": "answered", "verified": True,
            "glance": chunk["heading"], "body": chunk["text"],
            "citations": [{key: chunk[key] for key in ("chunk_id", "doc_id", "revision", "section")} |
                          {"quote": chunk["text"]}]}


def test_dataset_covers_four_categories_all_documents_and_valid_ground_truth():
    cases = evaluation.load_cases(ROOT / "eval/qa.jsonl")
    index = evaluation.citation_index()
    assert len(cases) == 36
    assert {c["category"] for c in cases} == {"answerable", "near-miss", "ambiguous", "off-domain"}
    assert len({c["doc_id"] for c in cases if c["expect"] == "answered"}) == 5
    assert sum(c["category"] == "near-miss" for c in cases) == 10
    for case in cases:
        result = evaluation.score_case(case, fixture_answer(case, index), index, 1)
        assert result.correct, (case["id"], result.reason)


@pytest.mark.asyncio
async def test_all_cases_use_text_and_independent_sessions_print_all_metrics(capsys):
    cases = evaluation.load_cases(ROOT / "eval/qa.jsonl")
    index = evaluation.citation_index()
    by_question = {case["q"]: case for case in cases}
    requests = []

    def handler(request):
        if request.url.path == "/v1/health":
            return httpx.Response(200, json={"ok": True, "mock": True})
        assert request.url.path == "/v1/ask"
        payload = json.loads(request.content)
        requests.append(payload)
        assert payload["audio"] is None and payload["text"]
        assert payload["revision"] is None  # Expected revision must not force retrieval.
        return httpx.Response(200, json=fixture_answer(by_question[payload["text"]], index))

    async with httpx.AsyncClient(base_url="http://fixture.invalid", transport=httpx.MockTransport(handler)) as client:
        results, evidence = await evaluation.run_suite(client, cases, index, allow_mock=True)
    metrics = evaluation.print_report(results, evidence)
    output = capsys.readouterr().out
    assert "MOCK/FIXTURE ONLY" in output
    assert "Answered-correct rate" in output and "not_found precision" in output and "not_found recall" in output
    assert "Citation-verification pass rate" in output and "Median latency" in output
    assert metrics["failed_cases"] == metrics["unverified_answers"] == 0
    assert evaluation.exit_code(metrics) == 0
    assert len({r["session_id"] for r in requests}) == 36


@pytest.mark.asyncio
async def test_mock_evidence_is_rejected_by_default():
    async with httpx.AsyncClient(base_url="http://fixture.invalid", transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"ok": True, "mock": True}))) as client:
        with pytest.raises(ValueError, match="Mock relay"):
            await evaluation.run_suite(client, [], {})


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(verified=False),
    lambda r: r.update(verified="true"),
    lambda r: r.update(citations=[]),
    lambda r: r["citations"][0].update(quote="A fabricated torque of 99 N-m"),
    lambda r: r["citations"][0].update(chunk_id="SOP-999:A:4.2"),
    lambda r: r["citations"][0].update(chunk_id=[]),
    lambda r: r["citations"][0].update(section="4.3"),
])
def test_unverified_answers_always_fail_the_safety_gate(mutation):
    case = evaluation.load_cases(ROOT / "eval/qa.jsonl")[0]
    index = evaluation.citation_index()
    response = fixture_answer(case, index)
    mutation(response)
    result = evaluation.score_case(case, response, index, 10)
    metrics = evaluation.summarize([result])
    assert metrics["unverified_answers"] == 1
    assert evaluation.exit_code(metrics) == 2


def test_wrong_numeric_answer_cannot_pass_substring_scoring():
    assert not evaluation.contains("Torque to 14 N-m", "4 N-m")
    assert not evaluation.contains("Torque to 0.4 N-m", "4 N-m")
    assert not evaluation.contains("Range begins at 3.84 N-m", "4 N-m")
    assert not evaluation.contains("Wait 160 s", "60 s")
    assert evaluation.contains("Keep it wet for 60 s.", "60 s")
    assert evaluation.contains("Use M5.", "M5")
    case = evaluation.load_cases(ROOT / "eval/qa.jsonl")[0]
    index = evaluation.citation_index()
    response = fixture_answer(case, index)
    response["body"] = "Torque in a star pattern to 14 N-m."
    response["glance"] = "Torque M5"
    assert not evaluation.score_case(case, response, index, 1).correct
    assert evaluation.exit_code(evaluation.summarize([
        evaluation.score_case(case, response, index, 1)])) == 2


def test_extra_unsupported_claim_fails_even_when_all_expected_words_are_present():
    case = evaluation.load_cases(ROOT / "eval/qa.jsonl")[0]
    index = evaluation.citation_index()
    response = fixture_answer(case, index)
    response["body"] += " Then apply 99 N-m."
    result = evaluation.score_case(case, response, index, 1)
    assert not result.correct and not result.citation_verified
    assert evaluation.exit_code(evaluation.summarize([result])) == 2


def test_draft_revision_cannot_be_cited_in_default_evaluation():
    case = evaluation.load_cases(ROOT / "eval/qa.jsonl")[0]
    index = evaluation.citation_index()
    response = fixture_answer(case | {"revision": "D"}, index)
    assert not evaluation.citations_verified(response, index)
    assert evaluation.citations_verified(response, index, forced_revision="D")


def test_ambiguous_questions_must_carry_clarification_signal():
    case = next(c for c in evaluation.load_cases(ROOT / "eval/qa.jsonl") if c["category"] == "ambiguous")
    response = fixture_answer(case, {})
    response.pop("needs_clarification")
    result = evaluation.score_case(case, response, {}, 1)
    assert not result.correct and result.reason == "missing needs_clarification"


def test_precision_recall_denominators_include_refusals_and_misses():
    R = evaluation.Result
    results = [
        R("a", "answerable", "answered", "answered", True, True, 10),
        R("b", "answerable", "answered", "not_found", False, False, 20),
        R("c", "near-miss", "not_found", "not_found", True, False, 30),
        R("d", "off-domain", "not_found", "answered", False, True, 40),
    ]
    metrics = evaluation.summarize(results)
    assert metrics["answered_correct_rate"] == metrics["not_found_precision"] == metrics["not_found_recall"] == 0.5
    assert metrics["citation_verification_pass_rate"] == 1
    assert metrics["median_latency_ms"] == 25
    assert evaluation.exit_code(metrics) == 1


def test_no_answers_does_not_report_perfect_citation_verification():
    metrics = evaluation.summarize([evaluation.Result(
        "u", "off-domain", "not_found", "not_found", True, False, 10)])
    assert metrics["citation_verification_pass_rate"] is None
    assert evaluation.percent(metrics["citation_verification_pass_rate"]) == "N/A"


@pytest.mark.asyncio
async def test_http_failure_payload_cannot_hide_an_unverified_answer():
    case = evaluation.load_cases(ROOT / "eval/qa.jsonl")[0]

    def handler(request):
        if request.url.path == "/v1/health":
            return httpx.Response(200, json={"ok": True, "mock": False})
        return httpx.Response(500, json={"trace_id": "broken", "outcome": "answered", "verified": False})

    async with httpx.AsyncClient(base_url="http://fixture.invalid", transport=httpx.MockTransport(handler)) as client:
        results, _ = await evaluation.run_suite(client, [case], evaluation.citation_index())
    assert evaluation.exit_code(evaluation.summarize(results)) == 2


@pytest.mark.asyncio
async def test_transport_failure_counts_as_a_failed_case():
    case = evaluation.load_cases(ROOT / "eval/qa.jsonl")[0]

    def handler(request):
        if request.url.path == "/v1/health":
            return httpx.Response(200, json={"ok": True, "mock": False})
        raise httpx.ReadTimeout("fixture failure")

    async with httpx.AsyncClient(base_url="http://fixture.invalid", transport=httpx.MockTransport(handler)) as client:
        results, _ = await evaluation.run_suite(client, [case], evaluation.citation_index())
    assert results[0].outcome == "error"
    assert evaluation.exit_code(evaluation.summarize(results)) == 1
