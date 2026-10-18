"""v3 clarify and scope (BUILD-PLAN-V3 section 2, README-V3-PART-2 sections 3, 4.1, 4.5)."""

import pytest
from pydantic import ValidationError

from specs_relay.pipeline import clarify as C
from specs_relay.schemas import AskResponse, Chunk, Clarify, Latency, Scope, Step, Walkthrough
from _relay_helpers import ask, make_client, sid

SYRUP = "how many pumps of syrup"


def chunk(section, heading, doc="SOP-230", title="Drink Recipes"):
    return Chunk(chunk_id=f"{doc}:C:{section}", doc_id=doc, revision="C", section=section,
                 heading=heading, text="t", title=title)


# --- the contract ---------------------------------------------------------------------

def test_clarify_caps():
    Clarify(prompt="Which one?", options=["Latte", "Cappuccino", "Iced latte"])
    for bad in ({"prompt": "x" * 41, "options": ["A", "B"]},
                {"prompt": "Which?", "options": ["A"]},
                {"prompt": "Which?", "options": ["A", "B", "C", "D"]},
                {"prompt": "Which?", "options": ["A", "x" * 25]},
                {"prompt": "Which?", "options": ["Latte", "latte"]},
                {"prompt": "Which?", "options": ["Café", "Latte"]}):
        with pytest.raises(ValidationError):
            Clarify(**bad)


def test_clarify_only_on_not_found_with_needs_clarification():
    c = Clarify(prompt="Which one?", options=["Latte", "Cappuccino"])
    base = dict(trace_id="t", transcript="q", intent="question", glance="", body="", source="",
                citations=[], verified=False, latency_ms=Latency())
    AskResponse(outcome="not_found", needs_clarification=True, clarify=c, **base)
    for outcome, needs in (("not_found", False), ("error", True)):
        with pytest.raises(ValidationError, match="clarify is sent only"):
            AskResponse(outcome=outcome, needs_clarification=needs, clarify=c, **base)


def test_scope_must_contain_the_index():
    steps = [Step(step_id=f"D:C:{i}", label=str(i), glance="g", body="b") for i in range(5)]
    Walkthrough(doc_id="D", revision="C", title="T", total=5, index=2, steps=steps, scope=Scope(start=2, end=5))
    for start, end, index in ((3, 5, 2), (2, 2, 2), (2, 6, 2), (-1, 3, 0)):
        with pytest.raises(ValidationError, match="scope"):
            Walkthrough(doc_id="D", revision="C", title="T", total=5, index=index, steps=steps,
                        scope=Scope(start=start, end=end))


# --- options are grounded ---------------------------------------------------------------

def test_options_are_heading_subjects_in_retrieval_order():
    chunks = [chunk("2.2", "Latte: add syrup"), chunk("3.1", "Cappuccino specifications"),
              chunk("6.2", "Iced latte: add syrup and milk"), chunk("2.3", "Latte: pull espresso")]
    c = C.build_clarify(chunks, str)
    assert c == Clarify(prompt="Which one?", options=["Latte", "Cappuccino", "Iced latte"])
    assert all(C.grounded(o, chunks) for o in c.options)


def test_at_most_three_options_and_over_long_subjects_are_skipped():
    chunks = [chunk("1", "A: x"), chunk("2", "A very long heading subject indeed: x"), chunk("3", "B: x"),
              chunk("4", "C: x"), chunk("5", "D: x")]
    assert C.build_clarify(chunks, str).options == ["A", "B", "C"]


def test_titles_when_the_top_document_offers_one_choice():
    chunks = [chunk("2.2", "Latte: add syrup"), chunk("4.1", "Steam milk", "SOP-220", "Shot and Milk")]
    c = C.build_clarify(chunks, str)
    assert c == Clarify(prompt="Which procedure?", options=["Drink Recipes", "Shot and Milk"])


def test_fewer_than_two_grounded_options_means_no_clarify():
    assert C.build_clarify([chunk("2.2", "Latte: add syrup"), chunk("2.3", "Latte: pour")], str) is None
    assert C.build_clarify([], str) is None


def test_an_invented_option_is_never_grounded():
    chunks = [chunk("2.2", "Latte: add syrup"), chunk("3.1", "Cappuccino specifications")]
    assert not C.grounded("Mocha", chunks)
    assert C.grounded("cappuccino", chunks) and C.grounded("Drink Recipes", chunks)


# --- replies ----------------------------------------------------------------------------

CL = Clarify(prompt="Which one?", options=["Latte", "Cappuccino", "Iced latte"])


@pytest.mark.parametrize("reply", ["cappuccino", "the iced latte", "Latte please", "um, the cappuccino one",
                                   "the iced latte for a large"])
def test_short_or_naming_replies_resolve(reply):
    assert C.resolves(CL, reply)


@pytest.mark.parametrize("reply", ["what temperature should the steam wand be for milk",
                                   "how long do I steam the milk for a large cappuccino drink today", ""])
def test_long_new_questions_do_not_resolve(reply):
    assert not C.resolves(CL, reply)


def test_combined_question():
    assert C.combined_question("How many pumps of syrup?", "cappuccino") == "How many pumps of syrup? cappuccino"
    assert C.combined_question("how many pumps of syrup", " latte ") == "how many pumps of syrup? latte"


# --- the three canned cases Part 1 mocks, through the real /v1/ask ----------------------

def test_ambiguous_question_returns_grounded_options():
    client, _ = make_client()
    b = ask(client, SYRUP).json()
    assert (b["outcome"], b["needs_clarification"], b["verified"]) == ("not_found", True, False)
    assert b["clarify"] == {"prompt": "Which one?", "options": ["Latte", "Cappuccino", "Iced latte"]}


def test_the_reply_is_answered_as_the_original_question():
    client, app = make_client()
    s = sid()
    ask(client, SYRUP, s)
    b = ask(client, "latte", s).json()
    assert b["outcome"] == "answered" and b["verified"] is True
    assert b["transcript"] == "latte"                          # what the worker said
    assert b["citations"][0]["chunk_id"] == "SOP-230:C:1.3"   # the syrup pump amounts
    assert "pumps" in b["body"]


def test_clarify_state_is_per_session():
    client, _ = make_client()
    a, other = sid(), sid()
    ask(client, SYRUP, a)
    b = ask(client, "latte", other).json()                   # another worker's "latte"
    assert b["citations"][0]["chunk_id"] == "SOP-230:C:2.1"  # plain retrieval, no combining


def test_a_long_reply_is_a_new_question_and_clears_the_clarify():
    client, _ = make_client()
    s = sid()
    ask(client, SYRUP, s)
    b = ask(client, "how tight is the m5 on the mounting bracket", s).json()
    assert b["citations"][0]["chunk_id"] == "SOP-114:C:4.2"
    later = ask(client, "latte", s).json()                     # the clarify is gone now
    assert later["citations"][0]["chunk_id"] == "SOP-230:C:2.1"


def test_spoken_walkthrough_is_scoped_to_the_section_asked_for():
    client, _ = make_client()
    b = ask(client, "walk me through making a cappuccino").json()
    w = b["walkthrough"]
    assert (b["outcome"], w["doc_id"]) == ("answered", "SOP-230")
    labels = [s["label"] for s in w["steps"]]
    assert labels[w["index"]] == "3.2"
    assert w["scope"] == {"start": labels.index("3.2"), "end": labels.index("3.4") + 1}
    assert len(w["steps"]) == w["total"] == 10                # steps stay the whole document


def test_a_whole_procedure_walkthrough_has_no_scope():
    client, _ = make_client()
    w = ask(client, "walk me through the bracket assembly").json()["walkthrough"]
    assert w["doc_id"] == "SOP-114" and w["scope"] is None
