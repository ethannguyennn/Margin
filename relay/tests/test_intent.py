import time

import pytest

from specs_relay.pipeline.intent import COMMAND_PHRASES, classify_intent, deviation_text, parse_command

# BUILD-PLAN-V2 section 3, verbatim.
COMMANDS = {
    "next": ["next", "done", "next step", "finished", "complete"],
    "back": ["back", "previous", "go back"],
    "repeat": ["repeat", "say that again"],
    "details": ["details", "more", "read it"],
    "diagram": ["diagram", "show diagram", "picture", "show me"],
    "pause": ["pause", "stop task"],
    "resume": ["resume", "continue"],
    "exit": ["exit", "close specs"],
}
# README-PART-4 section 3, plus near-misses of every command.
MUST_NOT_MATCH = [
    "what's the next step's torque",
    "go back to the torque value",
    "show me the M5 spec",
    "is this step done right",
    "repeat the warning about power",
    "next to the outlet collar",
    "how do I complete the gap check",
    "what does the diagram show for step 3",
    "is the picture rotated",
    "can I pause the pump while it runs",
    "continue torquing after the click",
    "where is the exit valve",
    "more torque on the upper left screw",
    "back off the gland nut",
]

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
# v1 repeat phrases that are not v2 commands keep the v1 `repeat` intent.
REPEAT = [
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


# --- v2 commands ---------------------------------------------------------------

@pytest.mark.parametrize("command, phrase", [(c, p) for c, ps in COMMANDS.items() for p in ps])
def test_every_build_plan_phrase_parses(command, phrase):
    assert parse_command(phrase) == command
    assert classify_intent(phrase) == "command"


@pytest.mark.parametrize("phrase, command", [
    ("Next.", "next"),
    ("NEXT STEP!", "next"),
    ("ok next", "next"),
    ("okay, next step please", "next"),
    ("um, go back", "back"),
    ("uh back", "back"),
    ("hey specs, show diagram", "diagram"),
    ("specs next", "next"),
    ("show me please", "diagram"),
    ("Close Specs.", "exit"),
    ("hey specs close specs", "exit"),
    ("  done  ", "next"),
])
def test_filler_case_and_punctuation(phrase, command):
    assert parse_command(phrase) == command


@pytest.mark.parametrize("t", MUST_NOT_MATCH)
def test_must_not_match_is_not_a_command(t):
    assert parse_command(t) is None
    assert classify_intent(t) == "question"


@pytest.mark.parametrize("phrase, command", [
    ("Go to the next step.", "next"),
    ("Okay, I'm done with this step.", "next"),
    ("all done", "next"),
    ("got it, move on", "next"),
    ("What's next?", "next"),
    ("next one please", "next"),
    ("go back a step", "back"),
    ("previous step", "back"),
    ("can you say that again?", "repeat"),
    ("read it again", "repeat"),
    ("one more time, repeat that", "repeat"),
    ("tell me more", "details"),
    ("show me the details", "details"),
    ("can you show me the picture?", "diagram"),
    ("let me see the diagram", "diagram"),
    ("hold on", "pause"),
    ("stop the task", "pause"),
    ("let's keep going", "resume"),
    ("I'm ready, start the task", "resume"),
    ("close the app", "exit"),
])
def test_natural_phrasing_is_a_command(phrase, command):
    assert parse_command(phrase) == command
    assert classify_intent(phrase) == "command"


@pytest.mark.parametrize("t", [
    "what's the next step for the milk",
    "how long do I steam the milk",
    "stop the grinder before cleaning?",
    "is the shot done at 36 grams",
    "do I need to hold the portafilter",
    "show me where the sanitizer goes",
    "more milk or less",
    "close the till at what time",
    "back of the machine",
])
def test_natural_phrasing_keeps_questions(t):
    assert parse_command(t) is None
    assert classify_intent(t) == "question"


@pytest.mark.parametrize("t", ["show me how to steam milk", "walk through closing the till",
                               "teach me how to pull a shot", "what are the steps for opening"])
def test_natural_walkthrough(t):
    assert classify_intent(t) == "walkthrough"


@pytest.mark.parametrize("t", ["", "  ", "...", None, "please", "um uh ok", "specs"])
def test_filler_only_is_not_a_command(t):
    assert parse_command(t) is None


def test_command_wins_before_v1_rules():
    # "say that again" was v1 `repeat`; as a whole-utterance command it is now `command`.
    assert classify_intent("say that again") == "command"
    # A v1 trigger that is not a command phrase is untouched.
    assert classify_intent("walk me through the seal swap") == "walkthrough"


def test_phrase_table_matches_build_plan():
    assert {c: sorted(ps) for c, ps in COMMAND_PHRASES.items()} == {c: sorted(ps) for c, ps in COMMANDS.items()}


# --- v1 intents ----------------------------------------------------------------

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
