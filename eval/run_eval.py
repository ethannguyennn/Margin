"""Evaluate the real /v1/ask text path. Exit 2 means an unverified answer escaped."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import statistics
import sys
import time
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from db.seed import load_corpus


def normalized(text: str) -> str:
    for before, after in (("°", " deg"), ("µ", "u"), ("μ", "u"), ("–", "-"), ("—", "-"),
                          ("·", "-"), ("“", '"'), ("”", '"'), ("’", "'")):
        text = text.replace(before, after)
    return " ".join(text.casefold().split())


def contains(text: str, expected: str) -> bool:
    expected = normalized(expected)
    if not expected:
        return False
    # Numeric suffixes are not matches: 4 N-m must not match 0.4 or 3.84 N-m.
    left = r"(?<![\w.])" if expected[0].isdigit() else r"(?<!\w)"
    right = r"(?!\w|\.\d)" if expected[-1].isdigit() else r"(?!\w)"
    return re.search(left + re.escape(expected) + right, normalized(text)) is not None


_PART = re.compile(r"\b[a-z]{1,5}-?\d+(?:\.\d+)?\b")
_VALUE = re.compile(
    r"(?<![\w.])(-?\d+(?:\.\d+)*)(?:\s*"
    r"(n-m|in-lb|ft-lb|mm|cm|um|kg|mg|ml|ul|ms|min|deg\s*c|deg\s*f|%|psi|rpm|hz|s|m|g|l))?"
    r"(?![a-z0-9]|\.\d)"  # a sentence-ending period still ends the value ("add $0.75.")
)


def fact_tokens(text: str) -> set[tuple[str, str]]:
    text = normalized(text)
    tokens = {(part, "part") for part in _PART.findall(text)}
    for value, unit in _VALUE.findall(_PART.sub(" ", text)):
        tokens.add((value, re.sub(r"\s+", "", unit)))
    return tokens


def values_supported(answer: str, quotes: list[str], sections: list[str], doc_ids: list[str]) -> bool:
    """Independent numeric audit: an asserted verified flag cannot hide 14 N-m."""
    support = fact_tokens(" ".join(quotes))
    bare_values = {value for value, unit in support if unit != "part"}
    labels = {part for section in sections for part in
              (".".join(section.split(".")[:n]) for n in range(1, len(section.split(".")) + 1))}
    support.update((doc_id.casefold(), "part") for doc_id in doc_ids)
    for value, unit in fact_tokens(answer):
        if (value, unit) in support:
            continue
        if not unit and value in bare_values | labels:
            continue
        return False
    return True


def load_cases(path: Path) -> list[dict]:
    cases = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        case = json.loads(line)
        if not isinstance(case, dict) or not isinstance(case.get("q"), str) or not case["q"].strip():
            raise ValueError(f"QA line {line_number}: a nonempty question is required")
        if case.get("expect") not in {"answered", "not_found"}:
            raise ValueError(f"QA line {line_number}: invalid expected outcome")
        if case.get("category") not in {"answerable", "near-miss", "ambiguous", "off-domain"}:
            raise ValueError(f"QA line {line_number}: invalid category")
        if case["expect"] == "answered" and any(not case.get(k) for k in ("doc_id", "revision", "section", "must_contain")):
            raise ValueError(f"QA line {line_number}: answered case needs citation and content expectations")
        case.setdefault("id", f"line-{line_number}")
        cases.append(case)
    if not cases or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("QA cases must be nonempty and have unique identifiers")
    return cases


def citation_index(corpus_dir: Path = ROOT / "corpus") -> dict[str, dict]:
    documents, chunks = load_corpus(corpus_dir)
    statuses = {(d["doc_id"], d["revision"]): d["status"] for d in documents}
    return {c["chunk_id"]: {**c, "status": statuses[c["doc_id"], c["revision"]]} for c in chunks}


def citations_verified(response: dict, index: dict, forced_revision: str | None = None) -> bool:
    """Audit the server's verification assertion against the local synthetic corpus."""
    citations = response.get("citations")
    if response.get("verified") is not True or not isinstance(citations, list) or not citations:
        return False
    quotes, sections, doc_ids = [], [], []
    for citation in citations:
        if not isinstance(citation, dict):
            return False
        if not isinstance(citation.get("chunk_id"), str):
            return False
        chunk = index.get(citation["chunk_id"])
        if chunk is None:
            return False
        if any(citation.get(key) != chunk[key] for key in ("doc_id", "revision", "section")):
            return False
        if forced_revision is None and chunk["status"] != "effective":
            return False
        if forced_revision is not None and chunk["revision"] != forced_revision:
            return False
        quote = citation.get("quote")
        if not isinstance(quote, str) or not contains(chunk["text"], quote):
            return False
        quotes.append(quote)
        sections.append(chunk["section"])
        doc_ids.append(chunk["doc_id"])
    glance, body = response.get("glance"), response.get("body")
    # The v2 generator intentionally omits body when the glance contains the answer.
    # Keep requiring a visible glance and independently audit every value/citation.
    if not isinstance(glance, str) or not glance.strip() or not isinstance(body, str):
        return False
    if len(glance) > 60 or len(body) > 450:
        return False
    return values_supported(glance + " " + body, quotes, sections, doc_ids)


@dataclass
class Result:
    id: str
    category: str
    expected: str
    outcome: str
    correct: bool
    citation_verified: bool
    latency_ms: float
    reason: str = ""


def score_case(case: dict, response: dict, index: dict, latency_ms: float) -> Result:
    outcome = response.get("outcome", "error")
    verified = outcome == "answered" and citations_verified(response, index, case.get("request_revision"))
    correct = outcome == case["expect"]
    reason = "" if correct else "unexpected outcome"
    if outcome == "answered":
        if not verified:
            correct, reason = False, "unverified answer"
        elif case["expect"] == "answered":
            matching = any(all(citation.get(key) == case[key] for key in ("doc_id", "revision", "section"))
                           for citation in response["citations"])
            text = str(response.get("glance", "")) + " " + str(response.get("body", ""))
            required = all(contains(text, value) for value in case["must_contain"])
            correct = matching and required
            if not correct:
                reason = "wrong citation or missing expected content"
    if case.get("needs_clarification") is True and response.get("needs_clarification") is not True:
        correct, reason = False, "missing needs_clarification"
    if outcome == "not_found" and (response.get("citations") != [] or response.get("verified") is not False):
        correct, reason = False, "not_found violates citation/verification contract"
    return Result(case["id"], case["category"], case["expect"], outcome, correct, bool(verified),
                  latency_ms, reason)


async def run_suite(client: httpx.AsyncClient, cases: list[dict], index: dict, *,
                    allow_mock: bool = False) -> tuple[list[Result], str]:
    health_response = await client.get("/v1/health")
    health_response.raise_for_status()
    health = health_response.json()
    if health.get("ok") is not True or not isinstance(health.get("mock"), bool):
        raise ValueError("Relay health must confirm ok and explicitly identify mock mode")
    if health["mock"] and not allow_mock:
        raise ValueError("Mock relay cannot produce live quality evidence; use --allow-mock for fixtures")
    evidence = "MOCK/FIXTURE ONLY" if health["mock"] else "LIVE RELAY"
    results = []
    for case in cases:
        started = time.perf_counter()
        try:
            response = await client.post("/v1/ask", json={
                "session_id": str(uuid4()), "text": case["q"], "audio": None,
                "revision": case.get("request_revision"),
                "context": {"doc_id": None, "step_id": None},
            })
            # Inspect bodies even on non-2xx: an unverified answered payload
            # must not escape the safety gate behind an HTTP error.
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Expected an object response")
            result = score_case(case, payload, index, (time.perf_counter() - started) * 1000)
            if not response.is_success:
                result.correct = False
                result.reason = f"HTTP {response.status_code}; {result.reason}".rstrip("; ")
            if not isinstance(payload.get("trace_id"), str) or not payload["trace_id"]:
                result.correct = False
                result.reason = "missing trace_id; " + result.reason
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            result = Result(case["id"], case["category"], case["expect"], "error", False, False,
                            (time.perf_counter() - started) * 1000, type(exc).__name__)
        results.append(result)
    return results, evidence


def ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def summarize(results: list[Result]) -> dict:
    answerable = [r for r in results if r.expected == "answered"]
    answers = [r for r in results if r.outcome == "answered"]
    predicted_nf = [r for r in results if r.outcome == "not_found"]
    expected_nf = [r for r in results if r.expected == "not_found"]
    true_nf = sum(r.expected == "not_found" for r in predicted_nf)
    return {
        "cases": len(results),
        "answered_correct_rate": ratio(sum(r.correct for r in answerable), len(answerable)),
        "not_found_precision": ratio(true_nf, len(predicted_nf)),
        "not_found_recall": ratio(true_nf, len(expected_nf)),
        "citation_verification_pass_rate": ratio(sum(r.citation_verified for r in answers), len(answers)),
        "median_latency_ms": statistics.median(r.latency_ms for r in results) if results else None,
        "answered": len(answers),
        "unverified_answers": sum(not r.citation_verified for r in answers),
        "failed_cases": sum(not r.correct for r in results),
        "category_passes": {name: {"passed": sum(r.correct for r in results if r.category == name), "total": count}
                            for name, count in sorted(Counter(r.category for r in results).items())},
    }


def exit_code(metrics: dict) -> int:
    if metrics["unverified_answers"]:
        return 2
    return 1 if metrics["failed_cases"] else 0


def percent(value) -> str:
    return "N/A" if value is None else f"{value:.1%}"


def print_report(results: list[Result], evidence: str) -> dict:
    metrics = summarize(results)
    print(f"Evidence: {evidence}; {metrics['cases']} questions; latency is HTTP round-trip.")
    print("Metric                              Result")
    for label, key in (("Answered-correct rate", "answered_correct_rate"),
                       ("not_found precision", "not_found_precision"),
                       ("not_found recall", "not_found_recall"),
                       ("Citation-verification pass rate", "citation_verification_pass_rate")):
        print(f"{label:<35} {percent(metrics[key]):>8}")
    latency = "N/A" if metrics["median_latency_ms"] is None else f"{metrics['median_latency_ms']:.1f} ms"
    print(f"{'Median latency':<35} {latency:>8}")
    for name, counts in metrics["category_passes"].items():
        print(f"  {name}: {counts['passed']}/{counts['total']} passed")
    for result in results:
        if not result.correct:
            print(f"  FAIL {result.id}: {result.reason}")
    print(f"Specs [{evidence}]: {metrics['cases']} questions; "
          f"answered-correct {percent(metrics['answered_correct_rate'])}; "
          f"not_found P/R {percent(metrics['not_found_precision'])}/{percent(metrics['not_found_recall'])}; "
          f"citation pass {percent(metrics['citation_verification_pass_rate'])}; "
          f"median {latency}; {metrics['unverified_answers']} unverified answers.")
    return metrics


async def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Relay origin, without /v1")
    parser.add_argument("--qa", type=Path, default=ROOT / "eval/qa.jsonl")
    parser.add_argument("--allow-mock", action="store_true", help="Label all results as fixture-only evidence")
    parser.add_argument("--output", type=Path, help="Write metrics and per-case outcomes as JSON")
    args = parser.parse_args(argv)
    cases = load_cases(args.qa)
    async with httpx.AsyncClient(base_url=args.base_url.rstrip("/"), timeout=30) as client:
        results, evidence = await run_suite(client, cases, citation_index(), allow_mock=args.allow_mock)
    # An explicit fixture flag may never accidentally produce a LIVE label.
    if args.allow_mock:
        evidence = "MOCK/FIXTURE ONLY"
    metrics = print_report(results, evidence)
    if args.output:
        args.output.write_text(json.dumps({"evidence": evidence, "metrics": metrics,
                                          "results": [asdict(r) for r in results]}, indent=2) + "\n",
                               encoding="utf-8")
    return exit_code(metrics)


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(f"Evaluation unavailable ({type(exc).__name__}); check relay health and the scaffold. "
              "No live quality metrics were produced.", file=sys.stderr)
        raise SystemExit(1)
