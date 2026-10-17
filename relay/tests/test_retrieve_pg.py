"""Retrieval SQL against a real Postgres + pgvector, using Part 5's README
schema in a throwaway schema. Hand-made embeddings, so no Gemini needed.

Opt-in: set MARGIN_TEST_PG_DSN to a database where the ``vector`` extension
exists (or can be created). The DSN is a test-only variable; the relay itself
gets DATABASE_URL from Part 3's config.
"""

import asyncio
import os
import sys

import pytest

DSN = os.environ.get("MARGIN_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="MARGIN_TEST_PG_DSN not set")
pytest.importorskip("psycopg_pool")
schemas = pytest.importorskip("margin_relay.schemas")

from margin_relay.pipeline.retrieve import PgStore, Retriever, should_refuse  # noqa: E402

DIM = 768
SCHEMA = "part4_it"

DDL = f"""
DROP SCHEMA IF EXISTS {SCHEMA} CASCADE;
CREATE SCHEMA {SCHEMA};
SET search_path = {SCHEMA}, public;
CREATE TABLE documents (
  doc_id text, revision text, title text NOT NULL,
  status text NOT NULL CHECK (status IN ('effective','superseded','draft')),
  effective_date date, PRIMARY KEY (doc_id, revision));
CREATE TABLE chunks (
  chunk_id text PRIMARY KEY, doc_id text NOT NULL, revision text NOT NULL, section text NOT NULL,
  is_step boolean NOT NULL DEFAULT false, step_order int, heading text, text text NOT NULL,
  tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(heading,'') || ' ' || text)) STORED,
  embedding vector({DIM}),
  FOREIGN KEY (doc_id, revision) REFERENCES documents(doc_id, revision));
CREATE INDEX ON chunks USING gin (tsv);
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);
"""

DOCS = [
    ("SOP-114", "C", "Mounting bracket assembly", "effective"),
    ("SOP-114", "B", "Mounting bracket assembly", "superseded"),
    ("SOP-120", "B", "Cleaning and disinfection", "effective"),
]
# (chunk_id, is_step, step_order, heading, text, axis of its one-hot embedding)
CHUNKS = [
    ("SOP-114:C:4.1", True, 1, "Preparation", "Seat the bracket on the two dowel pins.", 0),
    ("SOP-114:C:4.2", True, 2, "Fastening",
     "Torque all four M5 bracket screws to 4 N-m in a star pattern using a calibrated torque wrench.", 1),
    ("SOP-114:C:4.3", True, 3, "Witness marking", "Apply a torque stripe across each screw head.", 2),
    ("SOP-114:C:1", False, None, "Scope", "This procedure covers the HX-2 mounting bracket.", 3),
    ("SOP-114:B:4.2", True, 2, "Fastening", "Torque all four M5 bracket screws to 3 N-m.", 1),
    ("SOP-120:B:3.1", True, 1, "Rinse", "Rinse the wetted path with purified water at 60 degC for 5 min.", 4),
]


def onehot(i, lean=None):
    v = [0.0] * DIM
    v[i] = 1.0
    if lean is not None:
        v[lean] = 0.3
    return v


def lit(v):
    return "[" + ",".join(map(str, v)) + "]"


def run(coro):
    # psycopg async needs a selector loop on Windows.
    if sys.platform == "win32":
        return asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
    return asyncio.run(coro)


class Emb:
    dim = DIM

    def __init__(self, vec):
        self.vec = vec

    async def embed_query(self, text):
        return self.vec


async def with_pool(fn):
    from psycopg_pool import AsyncConnectionPool

    async with AsyncConnectionPool(DSN, open=False, kwargs={"options": f"-c search_path={SCHEMA},public"}) as pool:
        await pool.open()
        async with pool.connection() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            for stmt in [s for s in DDL.split(";") if s.strip()]:
                await conn.execute(stmt)
            for d in DOCS:
                await conn.execute("INSERT INTO documents VALUES (%s,%s,%s,%s,NULL)", d)
            for cid, step, order, heading, text, axis in CHUNKS:
                doc, rev, sec = cid.split(":")
                await conn.execute(
                    "INSERT INTO chunks (chunk_id, doc_id, revision, section, is_step, step_order, heading, "
                    "text, embedding) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)",
                    (cid, doc, rev, sec, step, order, heading, text, lit(onehot(axis))),
                )
        return await fn(pool)


def test_vector_leg_orders_by_cosine_and_filters_effective():
    async def go(pool):
        return await PgStore(pool).vector_top(onehot(1, lean=0), 20, None)

    rows = run(with_pool(go))
    ids = [r["chunk_id"] for r in rows]
    assert ids[0] == "SOP-114:C:4.2"
    assert ids[1] == "SOP-114:C:4.1"
    assert rows[0]["score"] == pytest.approx(1 / (1 + 0.09) ** 0.5, abs=1e-4)
    assert "SOP-114:B:4.2" not in ids          # superseded revision excluded


def test_forced_revision_overrides_status():
    async def go(pool):
        return await PgStore(pool).vector_top(onehot(1), 20, "B")

    rows = run(with_pool(go))
    assert {r["revision"] for r in rows} == {"B"}
    assert rows[0]["chunk_id"] == "SOP-114:B:4.2"


def test_lexical_leg_matches_a_spoken_question():
    async def go(pool):
        store = PgStore(pool)
        return (await store.fts_top("how tight is the m5 on the mounting bracket", 20, None),
                await store.fts_top("torque for the m5 bracket screws", 20, None),
                await store.fts_top("what's the wifi password", 20, None))

    spoken, specific, none = run(with_pool(go))
    # OR'ed lexemes: 'tight' | 'm5' | 'mount' | 'bracket'. 4.2 (m5, bracket) ties
    # the scope chunk (mounting bracket); the vector leg breaks that tie.
    assert "SOP-114:C:4.2" in [r["chunk_id"] for r in spoken[:2]]
    assert spoken[0]["score"] == spoken[1]["score"]
    assert specific[0]["chunk_id"] == "SOP-114:C:4.2"
    assert all(r["revision"] == "C" or r["doc_id"] != "SOP-114" for r in spoken + specific)
    assert none == []


def test_retriever_end_to_end_and_gate():
    async def go(pool):
        on_doc = await Retriever.from_pool(pool, Emb(onehot(1))).retrieve(
            "how tight is the m5 on the mounting bracket", None)
        off_doc = await Retriever.from_pool(pool, Emb(onehot(700))).retrieve("what's the wifi password", None)
        return on_doc, off_doc

    on_doc, off_doc = run(with_pool(go))
    assert isinstance(on_doc, schemas.RetrievalResult)
    assert on_doc.chunks[0].chunk_id == "SOP-114:C:4.2"
    assert on_doc.best_sim == pytest.approx(1.0, abs=1e-6)
    assert on_doc.best_rrf == pytest.approx(1 / 61 + 1 / 62)  # vector rank 1, lexical rank 2 (tie)
    assert len(on_doc.chunks) <= 6
    assert off_doc.best_sim == pytest.approx(0.0, abs=1e-6)
    assert off_doc.best_rrf <= 1 / 61                       # vector leg only
    assert should_refuse(off_doc.best_sim, off_doc.best_rrf, min_sim=0.6, min_rrf=0.03)
    assert not should_refuse(on_doc.best_sim, on_doc.best_rrf, min_sim=0.6, min_rrf=0.03)


def test_steps_for_returns_ordered_effective_steps():
    async def go(pool):
        return await Retriever.from_pool(pool, Emb(onehot(0))).steps_for("SOP-114", None)

    steps = run(with_pool(go))
    assert [s.step_id for s in steps] == ["SOP-114:C:4.1", "SOP-114:C:4.2", "SOP-114:C:4.3"]
    assert [s.label for s in steps] == ["4.1", "4.2", "4.3"]
