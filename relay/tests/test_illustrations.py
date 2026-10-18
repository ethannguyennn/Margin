from pathlib import Path

import pytest

from db.seed import load_corpus
from margin_relay.illustrations import available_graphics, catalog, graphic_for_chunk
from margin_relay.pipeline.generate import build_prompt, SYSTEM_PROMPT
from margin_relay.pipeline.verify import verify
from margin_relay.schemas import Draft
from margin_relay.walkthrough import step_from_chunk
from test_ask_trust import M5, ScriptedGenerator, ask, client_for
from test_generate import CHUNKS, GOOD


def test_every_reference_is_grounded_in_the_exact_corpus_revision_and_has_packaged_art():
    documents, chunks = load_corpus()
    by_id = {c['chunk_id']: c for c in chunks}
    graphics = catalog()
    assert len({g['id'] for g in graphics}) == len(graphics)
    assert len({g['file'] for g in graphics}) == 5
    root = Path(__file__).resolve().parents[2]
    covered = set()
    for graphic in graphics:
        assert (root / 'app/src/assets/sops' / graphic['file']).read_bytes().startswith(b'\x89PNG')
        x, y, width, height = graphic['crop']
        assert 0 <= x < 1 and 0 <= y < 1 and 0 < width <= 1-x and 0 < height <= 1-y
        for ref in graphic['references']:
            chunk = by_id[ref['chunk_id']]
            assert ref['quote'] in chunk['text'], ref
            covered.add(chunk['doc_id'])
    assert covered == {d['doc_id'] for d in documents}


def test_prompt_only_offers_graphics_supported_by_retrieved_chunks():
    prompt = build_prompt(M5, CHUNKS[:1])
    assert 'bracket-fasteners' in prompt
    assert 'housing-cleaning' not in prompt
    assert 'graphic_id' in SYSTEM_PROMPT
    assert available_graphics([]) == []


def test_gemini_selected_reference_survives_real_route():
    with client_for(ScriptedGenerator({**GOOD, 'graphic_id': 'bracket-fasteners'})) as client:
        out = ask(client, M5)
    assert out['verified'] and out['graphic_id'] == 'bracket-fasteners'


@pytest.mark.parametrize('graphic_id', ['https://untrusted.test/picture.png', 'missing', 'housing-cleaning'])
def test_unknown_or_uncited_picture_is_rejected_and_never_returned(graphic_id):
    gen = ScriptedGenerator({**GOOD, 'graphic_id': graphic_id})
    with client_for(gen) as client:
        out = ask(client, M5)
    assert out['outcome'] == 'not_found' and out['graphic_id'] is None
    assert gen.calls == 2


def test_reference_needs_its_source_anchor_in_the_citation():
    draft = Draft.model_validate({**GOOD, 'graphic_id': 'bracket-fasteners',
        'glance': 'Use the specified torque', 'body': 'Use the specified torque.',
        'citations': [{'chunk_id': CHUNKS[0].chunk_id, 'quote': '4 N-m'}]})
    assert not verify(draft, CHUNKS).ok


def test_walkthrough_changes_from_screw_overview_to_gap_detail_without_generation():
    _, chunks = load_corpus()
    by_id = {c['chunk_id']: c for c in chunks}
    assert step_from_chunk(by_id['SOP-114:C:4.2']).graphic_id == 'bracket-fasteners'
    assert step_from_chunk(by_id['SOP-114:C:4.3']).graphic_id == 'bracket-gap'
    assert step_from_chunk(by_id['SOP-114:D:4.2']).graphic_id == 'bracket-fasteners'
    assert graphic_for_chunk({'chunk_id': 'SOP-114:X:4.2', 'text': CHUNKS[0].text}) is None
