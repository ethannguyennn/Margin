"""Generated layouts must survive the route and carry only cited SOP text."""
import pytest
from pydantic import ValidationError

from margin_relay.schemas import Draft
from margin_relay.pipeline.verify import verify
from test_ask_trust import M5, ScriptedGenerator, ask, client_for
from test_generate import CHUNKS, GOOD, C, ask as answer_question

CARD_GOOD = {**GOOD, "citations": [{"chunk_id": CHUNKS[0].chunk_id, "quote": CHUNKS[0].text}]}


@pytest.mark.parametrize("kind", ["checklist", "warning"])
def test_generated_card_reaches_the_client_and_repeat(kind):
    display = {"kind": kind, "items": [CHUNKS[0].text]}
    with client_for(ScriptedGenerator({**CARD_GOOD, "display": display})) as client:
        response = client.post('/v1/ask', json={
            'session_id': '11111111-1111-4111-8111-111111111111', 'text': M5})
        out = response.json()
        assert response.status_code == 200, out
        assert out["verified"] and out["display"] == display
        repeat = client.post('/v1/ask', json={
            'session_id': '11111111-1111-4111-8111-111111111111', 'text': 'say that again'})
        assert repeat.json()["display"] == display


@pytest.mark.parametrize("item", ["Torque M5 to 5 N-m", "Bypass the safety interlock."])
def test_uncited_card_text_is_rejected_even_when_answer_is_valid(item):
    gen = ScriptedGenerator({**GOOD, "display": {"kind": "warning", "items": [item]}})
    with client_for(gen) as client:
        out = ask(client, M5)
    assert out["outcome"] == "not_found" and not out["verified"]
    assert out.get("display") is None
    assert gen.calls == 2


@pytest.mark.parametrize("display", [
    {"kind": "html", "items": [CHUNKS[0].text]},
    {"kind": "warning", "items": []},
    {"kind": "checklist", "items": [CHUNKS[0].text] * 5},
    {"kind": "checklist", "items": ["x" * 181]},
])
def test_invalid_display_schema_fails_closed(display):
    with pytest.raises(ValidationError):
        Draft.model_validate({**GOOD, "display": display})


def test_existing_answer_remains_valid_without_display():
    assert verify(Draft.model_validate(GOOD), CHUNKS).ok


def test_standalone_generation_preserves_display():
    display = {"kind": "checklist", "items": [CHUNKS[0].text]}
    out = answer_question(ScriptedGenerator({**CARD_GOOD, "display": display}))
    assert out.verified and out.display.model_dump() == display


@pytest.mark.parametrize("item", ["Disconnect power.", "disconnect power while running."])
def test_card_cannot_drop_negation_or_conditions_from_a_source_sentence(item):
    chunk = C("SOP-114:C:4.2", "Do not disconnect power while running.")
    draft = Draft.model_validate({**GOOD, "glance": "Follow the power warning", "body": chunk.text,
        "citations": [{"chunk_id": chunk.chunk_id, "quote": chunk.text}],
        "display": {"kind": "warning", "items": [item]}})
    assert not verify(draft, [chunk]).ok


@pytest.mark.parametrize("source, item", [
    ("Keep temperature below -4 degC.", "Keep temperature below 4 degC."),
    ("Reject if pressure > 5 bar.", "Reject if pressure < 5 bar."),
])
def test_card_preserves_signs_and_comparisons(source, item):
    chunk = C("SOP-114:C:4.2", source)
    draft = Draft.model_validate({"answerable": True, "glance": "Follow the warning",
        "body": source, "citations": [{"chunk_id": chunk.chunk_id, "quote": source}],
        "display": {"kind": "warning", "items": [item]}})
    assert not verify(draft, [chunk]).ok
