"""4.3: correct answers the verifier used to reject (fixtures from the 2026-10-17 eval and
the 2026-10-18 diagnostic). Every fixture must pass; the matching hallucinations must not."""

import json
from pathlib import Path

import pytest

from specs_relay.pipeline.verify import check_draft

FIXTURES = [json.loads(line) for line in
            (Path(__file__).parent / "fixtures" / "verify-false-negatives.jsonl").read_text("utf-8").splitlines()
            if line.strip()]


@pytest.mark.parametrize("case", FIXTURES, ids=[c["id"] for c in FIXTURES])
def test_correct_answer_now_verifies(case):
    assert case["failed_with"], "a fixture records the reason it used to fail"
    reason, cites = check_draft(case["draft"], case["chunks"])
    assert reason is None, f"{case['id']}: {reason}"
    assert cites


EXTRA_HOT = FIXTURES[0]


def draft_with(glance, body="", quote=None):
    d = json.loads(json.dumps(EXTRA_HOT["draft"]))
    d["glance"], d["body"] = glance, body
    if quote is not None:
        d["citations"][0]["quote"] = quote
    return d


@pytest.mark.parametrize("glance", [
    "Extra hot is 150 F",           # wrong number
    "Extra hot is 160 C",           # right number, wrong scale
    "Extra hot is 71 F",            # the Celsius value with a Fahrenheit unit
    "Extra hot is 160",             # a bare number never borrows the quoted unit
    "Extra hot is 160 deg",         # degree without a scale is not 160 F
])
def test_temperature_hallucinations_still_fail(glance):
    reason, _ = check_draft(draft_with(glance), EXTRA_HOT["chunks"])
    assert reason and reason.startswith("unsupported_number"), (glance, reason)


def test_a_quote_with_a_changed_temperature_is_still_not_found():
    reason, _ = check_draft(draft_with("Extra hot is 160 F",
                                       quote='"Extra hot" is 165 F (71 C), which is the maximum.'),
                            EXTRA_HOT["chunks"])
    assert reason and reason.startswith("quote_not_found")
