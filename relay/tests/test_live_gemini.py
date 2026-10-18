"""Live Gemini checks. Skipped unless Part 3's config provides GEMINI_API_KEY
and the three model IDs; keys are read only through that config.

Run: pytest relay/tests/test_live_gemini.py -v
"""

import asyncio
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
pytestmark = pytest.mark.skipif(not _key, reason="GEMINI_API_KEY not configured")


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
    from margin_relay.pipeline.generate import GeminiGenerator, answer_question
    from test_generate import CHUNKS, FakeRetriever, retrieval

    gen = GeminiGenerator.from_settings(S)
    async def both():
        out = await answer_question("how tight is the m5 on the mounting bracket", FakeRetriever(retrieval()),
                                    gen, revision=None, min_sim=0.0, min_rrf=0.0)
        off = await answer_question("what torque for the M6 screws on the HX-3 motor mount", FakeRetriever(retrieval()),
                                    gen, revision=None, min_sim=0.0, min_rrf=0.0)
        return out, off

    out, off = asyncio.run(both())
    assert out.outcome == "answered", out.reasons
    assert out.verified and "4 N-m" in out.glance + out.body
    assert out.citations[0].chunk_id == "SOP-114:C:4.2"

    assert off.outcome in ("not_found", "clarify")
    assert not off.verified


@pytest.mark.parametrize("kind, text, question", [
    ("warning", "WARNING: Disconnect power before opening the guard.",
     "What safety warning applies before opening the guard?"),
    ("checklist", "Inspect the seal. Check the latch.",
     "Give me a checklist of both required checks."),
])
def test_live_generated_cards(kind, text, question):
    from margin_relay.pipeline.generate import GeminiGenerator, answer_question
    from test_generate import C, FakeRetriever, retrieval

    chunk = C("SOP-TEST:A:1", text)
    gen = GeminiGenerator.from_settings(S)
    out = asyncio.run(answer_question(question, FakeRetriever(retrieval(chunks=[chunk])),
                                      gen, revision=None, min_sim=0.0, min_rrf=0.0))
    assert out.outcome == "answered", out.reasons
    assert out.verified and out.display is not None
    assert out.display.kind == kind
    assert out.display.items


def test_live_visual_reference_selection():
    from db.seed import load_corpus
    from margin_relay.pipeline.generate import GeminiGenerator, answer_question
    from test_generate import C, FakeRetriever, retrieval

    _, source = load_corpus()
    row = next(c for c in source if c['chunk_id'] == 'SOP-114:C:4.2')
    chunk = C(row['chunk_id'], row['text'])
    gen = GeminiGenerator.from_settings(S)
    out = asyncio.run(answer_question('How tight should I torque the M5 bracket screws?',
        FakeRetriever(retrieval(chunks=[chunk])), gen, revision=None, min_sim=0, min_rrf=0))
    assert out.verified, out.reasons
    assert out.graphic_id == 'bracket-fasteners'
