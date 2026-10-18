"""Shared glyph fixtures: the app's glyphs.ts suite runs the same JSON file."""

import json
from pathlib import Path

import pytest

from margin_relay.pipeline.sanitize import G2_ALLOWED_NON_ASCII, REPLACEMENTS, sanitize

CASES = json.loads((Path(__file__).parent / "fixtures" / "glyph_cases.json").read_text("utf-8"))


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_shared_fixture(case):
    assert sanitize(case["in"]) == case["out"]


def test_output_is_ascii_or_allow_listed():
    sample = "".join(chr(cp) for cp in range(0x80, 0x3000)) + "\U0001F600\U0001F44D"
    assert all(ch < "\x80" or ch in G2_ALLOWED_NON_ASCII for ch in sanitize(sample))


def test_replacements_are_ascii():
    assert all(out.isascii() for out in REPLACEMENTS.values())


def test_allow_list_has_29_glyphs():
    assert len(G2_ALLOWED_NON_ASCII) == 29


def test_idempotent():
    for case in CASES:
        once = sanitize(case["in"])
        assert sanitize(once) == once


APP_FIXTURES = Path(__file__).resolve().parents[2] / "app" / "tests" / "sanitize-fixtures.json"


@pytest.mark.skipif(not APP_FIXTURES.exists(), reason="app fixtures not in this checkout")
def test_relay_agrees_with_every_app_fixture():
    # TODO.md section 4: the app's own suite, run against the relay sanitizer.
    cases = json.loads(APP_FIXTURES.read_text("utf-8"))
    mismatches = [c for c in cases if sanitize(c["input"]) != c["output"]]
    assert mismatches == []
