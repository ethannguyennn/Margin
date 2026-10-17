import time

import pytest

from margin_relay.pipeline.intent import classify_intent, deviation_text

WALKTHROUGH = [
    "guide me through the bracket assembly",
    "Walk me through SOP-114",
    "show me the cleaning procedure step by step",
    "take me through the receiving inspection",
    "start procedure for torque wrench calibration",
]
DEVIATION = [
    "log a deviation the bracket hole is out of round",
    "Log deviation: seal was missing",
    "report an issue with the pump housing",
    "report a problem, gasket torn",
    "report nonconformance on lot 42",
    "report an nonconformance on lot 42",
    "flag this, wrong part number on the label",
]
REPEAT = [
    "repeat",
    "Repeat that please",
    "say that again",
    "can you say that again?",
    "what was that",
    "sorry, what was that?",
]
QUESTION = [
    "how tight is the m5 on the mounting bracket",
    "what temperature for the rinse water",
]
# Look like a trigger but are questions.
NOT_TRIGGERS = [
    "what was that torque spec",
    "repeat the torque check at step five, what value",
    "how do I report the torque value",
    "is there a guide for the pump",
    "what flag goes on the housing",
]


@pytest.mark.parametrize("t", WALKTHROUGH)
def test_walkthrough(t):
    assert classify_intent(t) == "walkthrough"


@pytest.mark.parametrize("t", DEVIATION)
def test_deviation(t):
    assert classify_intent(t) == "deviation"


@pytest.mark.parametrize("t", REPEAT)
def test_repeat(t):
    assert classify_intent(t) == "repeat"


@pytest.mark.parametrize("t", QUESTION + NOT_TRIGGERS)
def test_question(t):
    assert classify_intent(t) == "question"


@pytest.mark.parametrize("t", ["", "   ", "...", None])
def test_empty_is_unknown(t):
    assert classify_intent(t) == "unknown"


def test_first_match_wins():
    # walkthrough is checked before deviation
    assert classify_intent("walk me through how to flag this") == "walkthrough"


@pytest.mark.parametrize(
    "t, expected",
    [
        ("log a deviation the bracket hole is out of round", "the bracket hole is out of round"),
        ("Log deviation: seal was missing", "seal was missing"),
        ("report an issue with the pump housing", "with the pump housing"),
        ("flag this, wrong part number on the label", "wrong part number on the label"),
        ("ok so log a deviation that the gasket is torn.", "ok so the gasket is torn."),
        ("log a deviation", ""),
    ],
)
def test_deviation_text_strips_trigger(t, expected):
    assert deviation_text(t) == expected


def test_deviation_text_without_trigger_is_unchanged():
    assert deviation_text("  gasket torn ") == "gasket torn"


def test_sub_millisecond():
    t = "how tight is the m5 on the mounting bracket " * 3
    start = time.perf_counter()
    for _ in range(1000):
        classify_intent(t)
    assert (time.perf_counter() - start) / 1000 < 0.001
