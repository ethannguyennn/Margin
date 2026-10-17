import asyncio
import math

import pytest

from margin_relay.pipeline.retrieve import (
    GeminiEmbedder,
    Retriever,
    fuse,
    rrf_merge,
    should_refuse,
    step_from_row,
    tune_gate,
    vector_literal,
)

# --- RRF as a pure function -------------------------------------------------

def test_rrf_ranks_are_one_based():
    assert rrf_merge([["a"]]) == [("a", 1 / 61)]


def test_rrf_sums_across_lists():
    merged = dict(rrf_merge([["a", "b", "c"], ["b", "a", "d"]]))
    assert merged["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert merged["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert merged["c"] == pytest.approx(1 / 63)
    assert merged["d"] == pytest.approx(1 / 63)


def test_rrf_order_and_deterministic_ties():
    # a/b tie (best rank 1 each), c/d tie (best rank 3 each): first seen wins.
    assert [i for i, _ in rrf_merge([["a", "b", "c"], ["b", "a", "d"]])] == ["a", "b", "c", "d"]


def test_rrf_agreement_beats_a_single_top_hit():
    # 'x' is 2nd in both lists, 'v' and 'l' are 1st in only one.
    order = [i for i, _ in rrf_merge([["v", "x"], ["l", "x"]])]
    assert order[0] == "x"


def test_rrf_keeps_top_n():
    vec = [f"v{i}" for i in range(20)]
    lex = [f"l{i}" for i in range(20)]
    merged = rrf_merge([vec, lex], top_n=6)
    assert len(merged) == 6
    assert [i for i, _ in merged] == ["v0", "l0", "v1", "l1", "v2", "l2"]


def test_rrf_ignores_duplicates_within_a_list():
    assert dict(rrf_merge([["a", "a", "b"]])) == {"a": 1 / 61, "b": 1 / 62}


def test_rrf_empty():
    assert rrf_merge([[], []]) == []


def test_rrf_custom_k():
    assert rrf_merge([["a"], ["a"]], k=0) == [("a", 2.0)]


# --- fuse: rows in, chunks + gate scores out --------------------------------

def row(cid, score):
    doc, rev, sec = cid.split(":")
    return {"chunk_id": cid, "doc_id": doc, "revision": rev, "section": sec, "text": cid, "sim": score}


def test_fuse_best_sim_comes_from_vector_leg_only():
    vec = [row("A:C:1", 0.71), row("A:C:2", 0.52)]
    lex = [row("A:C:2", 9.0)]  # lexical scores are not similarities
    rows, best_sim, best_rrf = fuse(vec, lex, top_n=6)
    assert best_sim == 0.71
    assert best_rrf == pytest.approx(1 / 62 + 1 / 61)
    assert [r["chunk_id"] for r in rows] == ["A:C:2", "A:C:1"]
    assert rows[0]["rrf"] == pytest.approx(best_rrf)


def test_fuse_reads_sim_from_schema_chunks():
    # Part 5's db.vector_top/fts_top return schemas.Chunk with `sim` set on the vector leg.
    from margin_relay.schemas import Chunk

    vec = [Chunk(chunk_id="A:C:1", doc_id="A", revision="C", section="1", text="t", sim=0.83)]
    lex = [Chunk(chunk_id="A:C:2", doc_id="A", revision="C", section="2", text="u")]
    rows, best_sim, best_rrf = fuse(vec, lex)
    assert best_sim == 0.83
    assert [Chunk.model_validate(r).rrf for r in rows] == [pytest.approx(1 / 61)] * 2


def test_fuse_accepts_legacy_score_key():
    assert fuse([{"chunk_id": "A:C:1", "score": 0.7}], [])[1] == 0.7


def test_fuse_empty_legs():
    assert fuse([], [], top_n=6) == ([], 0.0, 0.0)


# --- the not_found gate -----------------------------------------------------

@pytest.mark.parametrize(
    "sim, rrf, refuse",
    [
        (0.10, 0.010, True),   # below both -> refuse, no LLM
        (0.90, 0.010, False),  # strong vector match
        (0.10, 0.032, False),  # strong agreement between legs
        (0.60, 0.030, False),  # exactly at both thresholds is not below
    ],
)
def test_gate(sim, rrf, refuse):
    assert should_refuse(sim, rrf, min_sim=0.60, min_rrf=0.030) is refuse


def test_tune_gate_never_refuses_answerable_and_maximizes_refusals():
    samples = [
        (0.78, 0.0325, True), (0.66, 0.0300, True), (0.52, 0.0322, True),   # answerable
        (0.70, 0.0330, False),       # near-miss above an answerable on both: gate can't take it
        (0.31, 0.0164, False), (0.28, 0.0000, False), (0.45, 0.0161, False),  # off-domain
    ]
    min_sim, min_rrf, refused = tune_gate(samples)
    assert refused == 3
    for s, r, ok in samples:
        if ok:
            assert not should_refuse(s, r, min_sim, min_rrf)
    assert should_refuse(0.45, 0.0161, min_sim, min_rrf)


def test_tune_gate_with_nothing_separable_refuses_nothing():
    assert tune_gate([(0.5, 0.03, True), (0.6, 0.031, False)])[2] == 0


# --- Retriever against a fake store ----------------------------------------

class FakeStore:
    def __init__(self, vec, lex, steps=()):
        self.vec, self.lex, self.steps = vec, lex, list(steps)
        self.calls = []

    async def vector_top(self, q_embedding, k, revision):
        self.calls.append(("vector", len(q_embedding), k, revision))
        return self.vec[:k]

    async def fts_top(self, query, k, revision):
        self.calls.append(("fts", query, k, revision))
        return self.lex[:k]

    async def steps_for(self, doc_id, revision):
        self.calls.append(("steps", doc_id, revision))
        return self.steps


class FakeEmbedder:
    dim = 768

    def __init__(self):
        self.calls = 0

    async def embed_query(self, text):
        self.calls += 1
        return [0.0] * self.dim


def test_retriever_runs_both_legs_and_fuses():
    schemas = pytest.importorskip("margin_relay.schemas")
    store = FakeStore([row(f"A:C:{i}", 0.9 - i / 100) for i in range(20)],
                      [row(f"B:C:{i}", 5.0 - i) for i in range(20)])
    emb = FakeEmbedder()
    result = asyncio.run(Retriever(store, emb).retrieve("how tight is the m5", None))
    assert isinstance(result, schemas.RetrievalResult)
    assert len(result.chunks) == 6
    assert result.best_sim == pytest.approx(0.9)
    assert result.best_rrf == pytest.approx(1 / 61)
    assert emb.calls == 1
    assert ("vector", 768, 20, None) in store.calls
    assert ("fts", "how tight is the m5", 20, None) in store.calls


def test_retriever_passes_forced_revision_and_reuses_embedding():
    pytest.importorskip("margin_relay.schemas")
    store = FakeStore([row("A:D:1", 0.8)], [])
    emb = FakeEmbedder()
    asyncio.run(Retriever(store, emb).retrieve("q", "D", q_embedding=[0.1] * 768))
    assert emb.calls == 0
    assert all(c[-1] == "D" for c in store.calls)


def test_steps_for_maps_rows_in_order():
    pytest.importorskip("margin_relay.schemas")
    rows = [
        {"chunk_id": "SOP-114:C:4.1", "section": "4.1", "heading": "Preparation",
         "text": "Seat bracket on dowel pins.", "step_order": 1},
        {"chunk_id": "SOP-114:C:4.2", "section": "4.2", "heading": "Fastening",
         "text": "Torque all four M5 bracket screws to 4 N·m in a star pattern using a calibrated "
                 "torque wrench (see SOP-131).", "step_order": 2},
    ]
    steps = asyncio.run(Retriever(FakeStore([], [], rows), FakeEmbedder()).steps_for("SOP-114", None))
    assert [s.step_id for s in steps] == ["SOP-114:C:4.1", "SOP-114:C:4.2"]
    assert [s.label for s in steps] == ["4.1", "4.2"]
    assert steps[0].glance == "Seat bracket on dowel pins."
    assert steps[1].glance == "Fastening"           # first sentence too long for the lens
    assert "4 N-m" in steps[1].body                 # sanitized, never truncated mid-value


def test_step_from_row_drops_markdown_list_number():
    # Part 5's corpus writes each step as "2. Torque all four ..."
    s = step_from_row({"chunk_id": "SOP-114:C:4.4", "section": "4.4", "heading": "Apply witness marks",
                       "text": "4. Apply one blue witness line across each screw head and onto the bracket. "
                               "Each line must be continuous."})
    assert s["glance"] == "Apply witness marks"
    assert s["body"].startswith("Apply one blue witness line")
    s = step_from_row({"chunk_id": "X:A:1", "section": "1", "heading": None, "text": "1. Disconnect power."})
    assert s["glance"] == "Disconnect power."


def test_step_from_row_caps_body_on_a_sentence():
    long = ("Check the seal. " * 40).strip()
    s = step_from_row({"chunk_id": "X:A:1", "section": "1", "heading": None, "text": long})
    assert len(s["body"]) <= 450
    assert s["body"].endswith(".")
    assert len(s["glance"]) <= 60


# --- embedder ---------------------------------------------------------------

class FakeModels:
    def __init__(self, values):
        self.values, self.requests = values, []

    async def embed_content(self, *, model, contents, config):
        from types import SimpleNamespace as NS

        self.requests.append((model, contents, config))
        return NS(embeddings=[NS(values=v) for v in self.values])


class FakeClient:
    def __init__(self, values):
        from types import SimpleNamespace as NS

        self.aio = NS(models=FakeModels(values))


def test_embedder_normalizes_and_checks_dim():
    client = FakeClient([[3.0, 4.0] + [0.0] * 766])
    vec = asyncio.run(GeminiEmbedder(client, "gemini-embedding-001", 768).embed_query("m5 torque"))
    assert len(vec) == 768
    assert math.isclose(sum(x * x for x in vec), 1.0)
    model, contents, config = client.aio.models.requests[0]
    assert config.output_dimensionality == 768
    assert config.task_type == "RETRIEVAL_QUERY"
    assert contents == ["m5 torque"]


def test_embedder_v2_uses_prefix_not_task_type():
    client = FakeClient([[1.0] * 768])
    asyncio.run(GeminiEmbedder(client, "gemini-embedding-2", 768).embed_query("m5 torque"))
    _, contents, config = client.aio.models.requests[0]
    assert config.task_type is None
    assert contents == ["task: search result | query: m5 torque"]


def test_embedder_rejects_wrong_dimension():
    from margin_relay.pipeline.retrieve import EmbeddingError

    client = FakeClient([[1.0] * 3072])
    with pytest.raises(EmbeddingError):
        asyncio.run(GeminiEmbedder(client, "gemini-embedding-001", 768).embed_query("x"))


def test_vector_literal():
    assert vector_literal([0.5, -1.0, 1e-9]) == "[0.5,-1,1e-09]"
