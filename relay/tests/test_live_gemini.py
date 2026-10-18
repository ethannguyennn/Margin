"""Live Gemini checks. Skipped unless Part 3's config provides GEMINI_API_KEY
and the three model IDs; keys are read only through that config.

Run: MARGIN_LIVE_GEMINI=1 pytest relay/tests/test_live_gemini.py -v
"""

import asyncio
import os
from pathlib import Path

import pytest

config = pytest.importorskip("margin_relay.config")
schemas = pytest.importorskip("margin_relay.schemas")


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
pytestmark = [pytest.mark.skipif(os.environ.get("MARGIN_LIVE_GEMINI") != "1",
                                 reason="live Gemini tests are opt-in: MARGIN_LIVE_GEMINI=1"),
              pytest.mark.skipif(not _key, reason="GEMINI_API_KEY not configured")]


def test_live_transcribe_fixture():
    from margin_relay.pipeline.transcribe import GeminiTranscriber

    pcm = (Path(__file__).parent / "fixtures" / "m5_question.pcm").read_bytes()
    text = asyncio.run(GeminiTranscriber.from_settings(S).transcribe(pcm, 16000)).lower()
    assert "m5" in text.replace(" ", "") or "m 5" in text
    assert "bracket" in text


def test_live_embedding_dimension_matches_config():
    from margin_relay.pipeline.generate import gemini_client
    from margin_relay.pipeline.retrieve import GeminiEmbedder

    emb = GeminiEmbedder(gemini_client(S.gemini_api_key), S.gemini_model_embed, S.embed_dim)
    async def both():  # one event loop: the SDK's aio session can't outlive asyncio.run
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
    from margin_relay.pipeline.generate import GeminiGenerator, answer_question
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
