from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from db.seed import load_corpus
from specs_relay.illustrations import available_graphics, catalog, graphic_for_chunk
from specs_relay.pipeline.generate import build_prompt, GeminiGenerator
from specs_relay.pipeline.verify import verify
from specs_relay.pipeline.sanitize import sanitize
from specs_relay.schemas import Chunk, Draft, RetrievalResult
from specs_relay.walkthrough import step_from_chunk
from specs_relay.routes.common import sanitized_step
from test_ask_trust import ScriptedGenerator, ask, client_for

ROOT = Path(__file__).resolve().parents[2]
_, CHUNKS = load_corpus()
SOURCE = next(c for c in CHUNKS if c['chunk_id'] == 'SOP-220:C:4.4')
CHUNK = Chunk(**{k: SOURCE[k] for k in ('chunk_id','doc_id','revision','section','heading','text')})
GOOD = dict(answerable=True, glance='Purge the steam wand for 2 seconds.', body=SOURCE['text'],
            citations=[dict(chunk_id=CHUNK.chunk_id, quote=SOURCE['text'])], graphic_id='milk-steaming')

def test_catalog_covers_every_current_sop_with_exact_source_anchors_and_packaged_art():
    docs, chunks = load_corpus(); by_id = {c['chunk_id']: c for c in chunks}; covered=set()
    assert len({g['id'] for g in catalog()}) == len(catalog())
    assert len({g['file'] for g in catalog()}) == 5
    for g in catalog():
        assert (ROOT/'app/src/assets/sops'/g['file']).read_bytes().startswith(b'\x89PNG')
        x,y,w,h=g['crop']; assert 0<=x<1 and 0<=y<1 and 0<w and 0<h and x+w<=1+1e-9 and y+h<=1+1e-9
        for ref in g['references']:
            c=by_id[ref['chunk_id']]; assert ref['quote'] in c['text']; covered.add(c['doc_id'])
    # SOP-231..300 are text-only on the lens until their corpus/figures are catalogued.
    assert covered == {f'SOP-{n}' for n in (201, 202, 210, 220, 230)} <= {d['doc_id'] for d in docs}

def test_prompt_and_walkthrough_keep_revision_and_source_binding():
    assert 'milk-steaming' in build_prompt('purge wand', [CHUNK])
    assert 'allergen-binder' not in build_prompt('purge wand', [CHUNK])
    assert available_graphics([]) == []
    step=step_from_chunk(SOURCE)
    assert step.graphic_id == 'milk-steaming'
    assert sanitized_step(NS(sanitize=sanitize),step).graphic_id == step.graphic_id
    assert graphic_for_chunk({**SOURCE, 'chunk_id':'SOP-220:X:4.4'}) is None
    assert graphic_for_chunk({**SOURCE, 'text':'Unrelated replacement content.'}) is None


@pytest.mark.parametrize('section, expected', [
    ('2.2', 'recipe-pumps'), ('2.3', 'espresso-shot'), ('2.4', 'milk-steaming'),
    ('3.2', 'espresso-shot'), ('3.3', 'milk-steaming'),
    ('4.2', 'espresso-shot'), ('4.3', 'milk-steaming'),
    ('5.3', 'espresso-shot'), ('6.3', 'recipe-cup'), ('6.4', 'espresso-shot'),
    ('7.2', 'recipe-pumps'), ('7.3', 'espresso-shot'), ('7.4', 'milk-steaming'),
    ('8.2', 'recipe-cup'), ('9.2', None),
])
def test_recipe_steps_use_action_specific_images(section, expected):
    chunk = next(c for c in CHUNKS if c['chunk_id'] == f'SOP-230:C:{section}')
    assert graphic_for_chunk(chunk) == expected
    assert step_from_chunk(chunk).graphic_id == expected
    assert [g['id'] for g in available_graphics([chunk])] == ([expected] if expected else [])

@pytest.mark.parametrize('graphic', ['https://unsafe.test/a.png','missing','allergen-binder'])
def test_rejects_unknown_or_uncited_graphic(graphic):
    assert not verify(Draft(**{**GOOD,'graphic_id':graphic}),[CHUNK]).ok

def test_citation_must_include_the_selected_visual_anchor():
    assert verify(Draft(**GOOD),[CHUNK]).ok
    assert not verify(Draft(**{**GOOD,'glance':'Purge it.','body':'Purge it.',
        'citations':[dict(chunk_id=CHUNK.chunk_id,quote='2 seconds')]}),[CHUNK]).ok

def test_selected_graphic_survives_real_ask_route():
    class Retriever:
        async def retrieve(self,*args): return RetrievalResult(chunks=[CHUNK],best_sim=.9,best_rrf=.04)
    with client_for(ScriptedGenerator(GOOD)) as client:
        client.app.state.pipeline.retriever=Retriever()
        out=ask(client,'How do I purge the steam wand?')
    assert out['verified'] and out['graphic_id']=='milk-steaming'

def test_generation_uses_configured_shared_timeout():
    gen=GeminiGenerator.from_settings(NS(gemini_api_key='',gemini_model_generate='test',generate_timeout_s=23),client=object())
    assert gen.timeout == 23


def _bake_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location('bake_lens', ROOT / 'app/scripts/bake-lens-graphics.py')
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def test_erase_regions_are_valid_fractions():
    for g in catalog():
        for x, y, w, h in g.get('erase', []):
            assert 0 <= x < 1 and 0 <= y < 1 and 0 < w and 0 < h and x + w <= 1 + 1e-9 and y + h <= 1 + 1e-9


def test_committed_lens_images_match_the_catalog_crops():
    # A crop or erase change without re-running app/scripts/bake-lens-graphics.py fails here.
    # Small tolerance: LANCZOS resampling can differ by a pixel or two across Pillow versions.
    from PIL import Image
    bake = _bake_module()
    for g in catalog():
        want, _ = bake.bake(g)
        got = Image.open(ROOT / 'app/src/assets/lens' / f"{g['id']}.png").convert('L')
        assert got.size == (288, 144)
        diff = sum(a != b for a, b in zip(got.tobytes(), want.tobytes()))
        assert diff <= 0.005 * 288 * 144, f"{g['id']}: {diff} pixels differ; re-run the bake script"
