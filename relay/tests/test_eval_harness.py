from pathlib import Path
import json

import httpx
import pytest

from part5_support import ROOT
from eval import run_eval as evaluation

# The industrial HX-2 bank these tests were written against (the demo bank in corpus/ is coffee).
HX2_CORPUS = Path(__file__).parent / "fixtures" / "hx2-corpus"
HX2_QA = HX2_CORPUS.parent / "hx2-qa.jsonl"


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
    cases = evaluation.load_cases(HX2_QA)
    index = evaluation.citation_index(HX2_CORPUS)
    assert len(cases) == 36
    assert {c["category"] for c in cases} == {"answerable", "near-miss", "ambiguous", "off-domain"}
    assert len({c["doc_id"] for c in cases if c["expect"] == "answered"}) == 5
    assert sum(c["category"] == "near-miss" for c in cases) == 10
    for case in cases:
        result = evaluation.score_case(case, fixture_answer(case, index), index, 1)
        assert result.correct, (case["id"], result.reason)


@pytest.mark.asyncio
async def test_all_cases_use_text_and_independent_sessions_print_all_metrics(capsys):
    cases = evaluation.load_cases(HX2_QA)
    index = evaluation.citation_index(HX2_CORPUS)
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
    case = evaluation.load_cases(HX2_QA)[0]
    index = evaluation.citation_index(HX2_CORPUS)
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
    case = evaluation.load_cases(HX2_QA)[0]
    index = evaluation.citation_index(HX2_CORPUS)
    response = fixture_answer(case, index)
    response["body"] = "Torque in a star pattern to 14 N-m."
    response["glance"] = "Torque M5"
    assert not evaluation.score_case(case, response, index, 1).correct
    assert evaluation.exit_code(evaluation.summarize([
        evaluation.score_case(case, response, index, 1)])) == 2


def test_extra_unsupported_claim_fails_even_when_all_expected_words_are_present():
    case = evaluation.load_cases(HX2_QA)[0]
    index = evaluation.citation_index(HX2_CORPUS)
    response = fixture_answer(case, index)
    response["body"] += " Then apply 99 N-m."
    result = evaluation.score_case(case, response, index, 1)
    assert not result.correct and not result.citation_verified
    assert evaluation.exit_code(evaluation.summarize([result])) == 2


def test_draft_revision_cannot_be_cited_in_default_evaluation():
    case = evaluation.load_cases(HX2_QA)[0]
    index = evaluation.citation_index(HX2_CORPUS)
    response = fixture_answer(case | {"revision": "D"}, index)
    assert not evaluation.citations_verified(response, index)
    assert evaluation.citations_verified(response, index, forced_revision="D")


def test_ambiguous_questions_must_carry_clarification_signal():
    case = next(c for c in evaluation.load_cases(HX2_QA) if c["category"] == "ambiguous")
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
    case = evaluation.load_cases(HX2_QA)[0]

    def handler(request):
        if request.url.path == "/v1/health":
            return httpx.Response(200, json={"ok": True, "mock": False})
        return httpx.Response(500, json={"trace_id": "broken", "outcome": "answered", "verified": False})

    async with httpx.AsyncClient(base_url="http://fixture.invalid", transport=httpx.MockTransport(handler)) as client:
        results, _ = await evaluation.run_suite(client, [case], evaluation.citation_index(HX2_CORPUS))
    assert evaluation.exit_code(evaluation.summarize(results)) == 2


@pytest.mark.asyncio
async def test_transport_failure_counts_as_a_failed_case():
    case = evaluation.load_cases(HX2_QA)[0]

    def handler(request):
        if request.url.path == "/v1/health":
            return httpx.Response(200, json={"ok": True, "mock": False})
        raise httpx.ReadTimeout("fixture failure")

    async with httpx.AsyncClient(base_url="http://fixture.invalid", transport=httpx.MockTransport(handler)) as client:
        results, _ = await evaluation.run_suite(client, [case], evaluation.citation_index(HX2_CORPUS))
    assert results[0].outcome == "error"
    assert evaluation.exit_code(evaluation.summarize(results)) == 1


def test_a_value_ending_its_sentence_in_the_quote_still_supports_the_answer():
    # Seen in the live demo-bank run: "add $0.75." ends the SOP sentence, the answer says it mid-sentence.
    assert evaluation.values_supported("Add $0.75 for oat milk.", ["Oat, almond, or soy milk: add $0.75."], ["4.3"], ["SOP-201"])
    assert evaluation.values_supported("Accept up to $50 bills", ["The largest bill we accept is $50."], ["2.2"], ["SOP-202"])
    assert not evaluation.values_supported("Add $0.85 for oat milk.", ["Oat, almond, or soy milk: add $0.75."], ["4.3"], ["SOP-201"])
    assert evaluation.fact_tokens("section 4.2.1 says 3.5.") >= {("3.5", "")}


@pytest.mark.asyncio
async def test_conversation_turns_share_only_their_session_and_every_ask_is_paced(monkeypatch):
    import asyncio
    cases = evaluation.load_cases(HX2_QA)[:2]
    cases[0] = {**cases[0], "turns": [cases[1]]}
    index = evaluation.citation_index(HX2_CORPUS)
    by_query = {c["q"]: c for c in cases}
    requests, sleeps = [], []
    async def sleep(seconds):
        sleeps.append(seconds)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    def handler(request):
        if request.url.path == "/v1/health":
            return httpx.Response(200, json={"ok": True, "mock": True})
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(200, json=fixture_answer(by_query[payload["text"]], index))
    async with httpx.AsyncClient(base_url="http://fixture.invalid", transport=httpx.MockTransport(handler)) as client:
        results, _ = await evaluation.run_suite(client, cases, index, allow_mock=True, pace=6)
    assert all(r.correct for r in results)
    assert all(r.response["verified"] is True for r in results)
    assert requests[0]["session_id"] == requests[1]["session_id"] != requests[2]["session_id"]
    assert sleeps == [6, 6]


@pytest.mark.asyncio
@pytest.mark.parametrize("pace", [-1, float("inf"), float("nan")])
async def test_invalid_pacing_is_rejected_before_any_request(pace):
    async with httpx.AsyncClient(base_url="http://fixture.invalid") as client:
        with pytest.raises(ValueError, match="pace"):
            await evaluation.run_suite(client, [], {}, pace=pace)


def test_gap_probe_import_is_offline_and_uses_scored_conversations(monkeypatch):
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: pytest.fail("import must not send requests"))
    from tools.diagnostic import gap_probe
    cases = gap_probe.cases()
    assert len(cases) == 12
    assert any(c["q"] == "Pull up the espresso standards." for c in cases)
    assert any(c.get("turns") for c in cases)
    assert any(c["q"] == "How many pumps of syrup?" and c["turns"][0]["q"] == "cappuccino" for c in cases)


def test_step_regression_import_is_offline_and_scores_all_18_asks(monkeypatch):
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: pytest.fail("import must not send requests"))
    from tools.diagnostic import clarify_rate
    cases = clarify_rate.cases()
    assert len(cases) == len({c["id"] for c in cases}) == 18
    assert all(c["context"]["step_id"] == f"SOP-210:C:{c['section']}" for c in cases)
    assert all(c["expect"] == "answered" and c["must_contain"] for c in cases)


@pytest.mark.parametrize("actual,expected", [("160deg F", "160\u00b0F"), ("160 Fahrenheit", "160 degF"),
    ("10 sec on", "10 seconds on"), ("4 h", "4 hours")])
def test_scoring_normalizes_unit_spelling_without_changing_values_or_units(actual, expected):
    assert evaluation.contains(actual, expected)
    assert not evaluation.contains(actual, expected.replace("160", "161").replace("10", "11").replace("4", "5"))
    assert not evaluation.contains("160 degC", "160 degF")
    assert not evaluation.contains("10 min", "10 sec")


def test_documented_equivalent_answers_still_require_the_right_fact():
    bank = {c["id"]: c for c in evaluation.load_cases(ROOT / "eval/qa.jsonl")}
    index = evaluation.citation_index()
    for case_id, section, glance, quote, wrong in [
        ("a24", "7.2", "First aid kit under back counter", "The first aid kit is under the back counter by the dish sink.", "First aid kit above back counter"),
        ("a25", "2.1", "Shot time: 25 to 30 sec", "Shot time | 25 to 30 seconds", "Shot time: 35 to 40 sec"),
    ]:
        case = bank[case_id]
        chunk = index[f"{case['doc_id']}:C:{section}"]
        response = {"outcome": "answered", "verified": True, "glance": glance, "body": "",
                    "citations": [{k: chunk[k] for k in ("chunk_id", "doc_id", "revision", "section")} | {"quote": quote}]}
        assert evaluation.score_case(case, response, index, 1).correct
        assert not evaluation.score_case(case, {**response, "glance": wrong}, index, 1).correct
