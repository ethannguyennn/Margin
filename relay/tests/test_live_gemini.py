"""Live Gemini checks. Skipped unless Part 3's config provides GEMINI_API_KEY
and the three model IDs; keys are read only through that config.

Run: SPECS_LIVE_GEMINI=1 pytest relay/tests/test_live_gemini.py -v
"""

import asyncio
import os
from pathlib import Path

import pytest

config = pytest.importorskip("specs_relay.config")
schemas = pytest.importorskip("specs_relay.schemas")


def _settings():
    if hasattr(config, "get_settings"):
        return config.get_settings()
    if hasattr(config, "settings"):
        return config.settings
    return config.Settings()


S = _settings()
_key = getattr(S, "gemini_api_key", None)
_key = _key.get_secret_value() if hasattr(_key, "get_secret_value") else _key
# Opt-in: a key in .env must not make `make test` spend quota or flake on 429s
# (the free tier allows 15 requests/min and 20/day on some models).
pytestmark = [pytest.mark.skipif(os.environ.get("SPECS_LIVE_GEMINI") != "1",
                                 reason="live Gemini tests are opt-in: SPECS_LIVE_GEMINI=1"),
              pytest.mark.skipif(not _key, reason="GEMINI_API_KEY not configured")]


def test_live_transcribe_fixture():
    from specs_relay.pipeline.transcribe import GeminiTranscriber

    pcm = (Path(__file__).parent / "fixtures" / "m5_question.pcm").read_bytes()
    text = asyncio.run(GeminiTranscriber.from_settings(S).transcribe(pcm, 16000)).lower()
    assert "m5" in text.replace(" ", "") or "m 5" in text
    assert "bracket" in text


def test_live_embedding_dimension_matches_config():
    from specs_relay.pipeline.generate import gemini_client
    from specs_relay.pipeline.retrieve import GeminiEmbedder

    emb = GeminiEmbedder(gemini_client(S.gemini_api_key), S.gemini_model_embed, S.embed_dim)

    async def both():
        # One event loop: the SDK's async client is bound to the loop it first ran on.
        q = await emb.embed_query("how tight is the m5 on the mounting bracket")
        docs = await emb.embed_documents(
            ["Torque all four M5 bracket screws to 4 N-m in a star pattern.",
             "Rinse the wetted path with purified water at 60 degC for 5 min."],
            ["Fastening", "Rinse"])
        return q, docs

    q, docs = asyncio.run(both())
    assert len(q) == int(S.embed_dim)
    cos = [sum(a * b for a, b in zip(q, d)) for d in docs]
    assert cos[0] > cos[1]


def test_live_generate_answers_and_refuses():
    from specs_relay.pipeline.generate import GeminiGenerator, answer_question
    from test_generate import CHUNKS, FakeRetriever, retrieval

    gen = GeminiGenerator.from_settings(S)
    out = asyncio.run(answer_question("how tight is the m5 on the mounting bracket", FakeRetriever(retrieval()),
                                      gen, revision=None, min_sim=0.0, min_rrf=0.0))
    assert out.outcome == "answered", out.reasons
    assert out.verified and "4 N-m" in out.glance + out.body
    assert out.citations[0].chunk_id == "SOP-114:C:4.2"

    off = asyncio.run(answer_question("what torque for the M6 screws on the HX-3 motor mount", FakeRetriever(retrieval()),
                                      gen, revision=None, min_sim=0.0, min_rrf=0.0))
    assert off.outcome in ("not_found", "clarify")
    assert not off.verified


def test_live_reference_graphics_for_current_corpus():
    import json
    import time
    from db.seed import load_corpus
    from specs_relay.pipeline.generate import GeminiGenerator, answer_question
    _, chunks = load_corpus()
    cases = [
        ('SOP-201:C:2.3', 'Where is the receipt printer and spare paper?', 'cashier-station'),
        ('SOP-202:C:7.5', 'What do we do with the bank bag?', 'till-closing'),
        ('SOP-210:C:3.7', 'Where is the test strip used?', 'sanitizer-test'),
        ('SOP-220:C:4.4', 'How do I purge the steam wand?', 'milk-steaming'),
        ('SOP-230:C:2.2', 'Where do I pump syrup for a latte?', 'recipe-pumps'),
    ]
    async def run():
        generator=GeminiGenerator.from_settings(S); rows=[]
        for cid, question, expected in cases:
            c=next(c for c in chunks if c['chunk_id']==cid)
            chunk=schemas.Chunk(**{k:c[k] for k in ('chunk_id','doc_id','revision','section','heading','text')})
            retrieved=schemas.RetrievalResult(chunks=[chunk],best_sim=.9,best_rrf=.04)
            start=time.perf_counter()
            out=await answer_question(question,None,generator,revision=None,min_sim=0,min_rrf=0,retrieval=retrieved)
            assert out.verified and out.graphic_id==expected, (cid,out.outcome,out.graphic_id,out.reasons)
            rows.append(dict(chunk_id=cid,question=question,graphic_id=out.graphic_id,verified=out.verified,
                             seconds=round(time.perf_counter()-start,2)))
        return rows
    rows=asyncio.run(run())
    print(json.dumps(rows))
    output=os.environ.get('SPECS_GRAPHICS_EVIDENCE')
    if output: Path(output).write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')
