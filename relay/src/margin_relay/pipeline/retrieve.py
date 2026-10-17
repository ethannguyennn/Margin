"""Hybrid retrieval: Gemini embedding + pgvector top-20 + full-text top-20,
fused with Reciprocal Rank Fusion to the top 6, plus the ``not_found`` gate.

The retriever takes its store as an argument. ``PgStore(pool)`` runs the SQL
below on a psycopg async pool (Part 5's); anything with the same three async
methods (``vector_top``, ``fts_top``, ``steps_for``) returning row dicts with a
``score`` works, which is how the unit tests run without a database.

Both legs are filtered to ``documents.status = 'effective'``, or to the forced
``revision`` when one is passed.
"""

from __future__ import annotations

import asyncio
import math
import re
from typing import Any, Protocol, Sequence

from .sanitize import sanitize

RRF_K = 60
LEG_K = 20
TOP_N = 6
EMBED_TIMEOUT_S = 2.0
GLANCE_MAX = 60
BODY_MAX = 450


class EmbeddingError(Exception):
    code = "llm_timeout"


class RetrievalError(Exception):
    code = "db_down"


# --- pure functions -----------------------------------------------------------

def rrf_merge(ranked: Sequence[Sequence[str]], k: int = RRF_K, top_n: int = TOP_N) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: ``score = sum(1 / (k + rank))``, ranks 1-based.

    Ties break on best single-list rank, then on first appearance, so the order
    is deterministic.
    """
    score: dict[str, float] = {}
    best_rank: dict[str, int] = {}
    first_seen: dict[str, int] = {}
    for ids in ranked:
        for rank, item in enumerate(dict.fromkeys(ids), start=1):  # dedupe, keep order
            score[item] = score.get(item, 0.0) + 1.0 / (k + rank)
            best_rank[item] = min(best_rank.get(item, rank), rank)
            first_seen.setdefault(item, len(first_seen))
    order = sorted(score, key=lambda i: (-score[i], best_rank[i], first_seen[i]))
    return [(i, score[i]) for i in order[:top_n]]


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def fuse(vec_rows: list[Any], lex_rows: list[Any], top_n: int = TOP_N) -> tuple[list[dict], float, float]:
    """Merge the two legs. Returns ``(rows, best_sim, best_rrf)``.

    ``best_sim`` is the top cosine similarity from the vector leg (lexical
    scores are not similarities); ``best_rrf`` is the top fused score.
    """
    by_id: dict[str, dict] = {}
    for r in [*vec_rows, *lex_rows]:
        d = dict(r) if isinstance(r, dict) else dict(vars(r))
        by_id.setdefault(d["chunk_id"], d)
    merged = rrf_merge([[_get(r, "chunk_id") for r in vec_rows], [_get(r, "chunk_id") for r in lex_rows]],
                       top_n=top_n)
    rows = [{**by_id[cid], "rrf": s} for cid, s in merged]
    best_sim = max((float(_get(r, "score") or 0.0) for r in vec_rows), default=0.0)
    best_rrf = merged[0][1] if merged else 0.0
    return rows, best_sim, best_rrf


def should_refuse(best_sim: float, best_rrf: float, min_sim: float, min_rrf: float) -> bool:
    """The not_found gate: refuse, without calling the LLM, only when *both*
    signals are weak."""
    return best_sim < min_sim and best_rrf < min_rrf


def vector_literal(vec: Sequence[float]) -> str:
    """pgvector text form, so no numpy/pgvector adapter is needed."""
    return "[" + ",".join(f"{x:.9g}" for x in vec) + "]"


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _first_sentence(text: str) -> str:
    return _SENTENCE_END.split(text.strip(), maxsplit=1)[0]


def _fit_sentences(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text
    out = ""
    for sentence in _SENTENCE_END.split(text):
        nxt = f"{out} {sentence}".strip()
        if len(nxt) > cap:
            break
        out = nxt
    # One enormous sentence: cut on a word, never mid-token.
    return out or text[: cap - 3].rsplit(" ", 1)[0] + "..."


def step_from_row(row: Any) -> dict:
    """Map a step chunk to the ``Step`` shape: lens-safe glance and body.

    The glance is the step's first sentence when it fits, else its heading --
    never a sentence cut mid-value ("Torque to 4 N-" is worse than "Fastening").
    """
    text = " ".join(sanitize(_get(row, "text") or "").split())
    heading = " ".join(sanitize(_get(row, "heading") or "").split())
    first = _first_sentence(text)
    if 0 < len(first) <= GLANCE_MAX:
        glance = first
    elif 0 < len(heading) <= GLANCE_MAX:
        glance = heading
    else:
        glance = _fit_sentences(first or heading, GLANCE_MAX)
    return {
        "step_id": _get(row, "chunk_id"),
        "label": str(_get(row, "section")),
        "glance": glance,
        "body": _fit_sentences(text, BODY_MAX),
    }


# --- embedding ----------------------------------------------------------------

class GeminiEmbedder:
    """Query/document embeddings at exactly ``dim`` dimensions, L2-normalized.

    ``gemini-embedding-001`` takes ``task_type`` and must be normalized by hand
    below 3072 dims; the ``gemini-embedding-2`` family rejects ``task_type``
    and uses text prefixes instead (ai.google.dev/gemini-api/docs/embeddings).
    Normalizing is harmless for either and cosine distance ignores it anyway.
    Part 5's seed must embed documents through ``embed_documents`` with the
    same model and dim, or the vector leg silently returns garbage.
    """

    def __init__(self, client: Any, model: str, dim: int, timeout: float = EMBED_TIMEOUT_S):
        if not model:
            raise ValueError("GEMINI_MODEL_EMBED is not set")
        self.client, self.model, self.dim, self.timeout = client, model, int(dim), timeout
        self._task_type = "embedding-001" in model or model.startswith("text-embedding")

    def _config(self, task_type: str):
        from google.genai import types

        return types.EmbedContentConfig(
            output_dimensionality=self.dim,
            task_type=task_type if self._task_type else None,
        )

    async def _embed(self, contents: list[str], task_type: str) -> list[list[float]]:
        try:
            resp = await asyncio.wait_for(
                self.client.aio.models.embed_content(
                    model=self.model, contents=contents, config=self._config(task_type)
                ),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError as e:
            raise EmbeddingError("embedding timed out") from e
        except Exception as e:  # SDK/network errors: typed, no prompt or key in the message
            raise EmbeddingError(f"embedding failed: {type(e).__name__}") from e
        out = []
        for emb in resp.embeddings:
            v = list(emb.values)
            if len(v) != self.dim:
                raise EmbeddingError(f"embedding has {len(v)} dims, EMBED_DIM is {self.dim}")
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        if len(out) != len(contents):
            raise EmbeddingError("embedding count mismatch")
        return out

    async def embed_query(self, text: str) -> list[float]:
        content = text if self._task_type else f"task: search result | query: {text}"
        return (await self._embed([content], "RETRIEVAL_QUERY"))[0]

    async def embed_documents(self, texts: list[str], titles: list[str | None] | None = None) -> list[list[float]]:
        titles = titles or [None] * len(texts)
        contents = texts if self._task_type else [
            f"title: {t or 'none'} | text: {x}" for t, x in zip(titles, texts)
        ]
        return await self._embed(contents, "RETRIEVAL_DOCUMENT")


# --- SQL store ----------------------------------------------------------------

_FILTER = """
  (CASE WHEN %(rev)s::text IS NULL THEN d.status = 'effective'
        ELSE c.revision = %(rev)s::text END)"""

_COLUMNS = "c.chunk_id, c.doc_id, c.revision, c.section, c.heading, c.text, c.is_step, c.step_order"

VECTOR_SQL = f"""
SELECT {_COLUMNS}, 1 - (c.embedding <=> %(q)s::vector) AS score
FROM chunks c
JOIN documents d ON d.doc_id = c.doc_id AND d.revision = c.revision
WHERE c.embedding IS NOT NULL AND {_FILTER}
ORDER BY c.embedding <=> %(q)s::vector, c.chunk_id
LIMIT %(k)s"""

# websearch_to_tsquery ANDs every term, so a spoken question ("how tight is
# the m5 on the mounting bracket") rarely matches one section verbatim. The
# lexemes it produces are OR'ed instead and ts_rank_cd rewards chunks hitting
# more of them. The ::tsquery cast re-parses without re-stemming.
LEXICAL_SQL = f"""
WITH q AS (
  SELECT replace(websearch_to_tsquery('english', %(q)s)::text, ' & ', ' | ')::tsquery AS tsq
)
SELECT {_COLUMNS}, ts_rank_cd(c.tsv, q.tsq) AS score
FROM chunks c
JOIN documents d ON d.doc_id = c.doc_id AND d.revision = c.revision
CROSS JOIN q
WHERE c.tsv @@ q.tsq AND {_FILTER}
ORDER BY score DESC, c.chunk_id
LIMIT %(k)s"""

STEPS_SQL = f"""
SELECT {_COLUMNS}
FROM chunks c
JOIN documents d ON d.doc_id = c.doc_id AND d.revision = c.revision
WHERE c.doc_id = %(doc)s AND c.is_step AND {_FILTER}
ORDER BY c.step_order, c.chunk_id"""


class Store(Protocol):
    async def vector_top(self, q_embedding: list[float], k: int, revision: str | None) -> list[Any]: ...
    async def fts_top(self, query: str, k: int, revision: str | None) -> list[Any]: ...
    async def steps_for(self, doc_id: str, revision: str | None) -> list[Any]: ...


class PgStore:
    """The two retrieval legs and the step query on a psycopg async pool."""

    def __init__(self, pool: Any):
        self.pool = pool

    async def _rows(self, sql: str, params: dict) -> list[dict]:
        from psycopg.rows import dict_row

        try:
            async with self.pool.connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(sql, params)
                    return list(await cur.fetchall())
        except Exception as e:
            raise RetrievalError(f"query failed: {type(e).__name__}") from e

    async def vector_top(self, q_embedding, k, revision):
        return await self._rows(VECTOR_SQL, {"q": vector_literal(q_embedding), "k": k, "rev": revision})

    async def fts_top(self, query, k, revision):
        return await self._rows(LEXICAL_SQL, {"q": query, "k": k, "rev": revision})

    async def steps_for(self, doc_id, revision):
        return await self._rows(STEPS_SQL, {"doc": doc_id, "rev": revision})


# --- the Retriever --------------------------------------------------------------

class Retriever:
    def __init__(self, store: Store, embedder: Any, leg_k: int = LEG_K, top_n: int = TOP_N):
        self.store, self.embedder, self.leg_k, self.top_n = store, embedder, leg_k, top_n

    @classmethod
    def from_pool(cls, pool: Any, embedder: Any, **kw) -> "Retriever":
        return cls(PgStore(pool), embedder, **kw)

    async def embed(self, query: str) -> list[float]:
        """Exposed so the orchestrator can time the ``embed`` span separately
        and pass the vector back in as ``q_embedding``."""
        return await self.embedder.embed_query(query)

    async def retrieve(self, query: str, revision: str | None, q_embedding: list[float] | None = None):
        from ..schemas import Chunk, RetrievalResult

        if q_embedding is None:
            q_embedding = await self.embed(query)
        vec_rows, lex_rows = await asyncio.gather(
            self.store.vector_top(q_embedding, self.leg_k, revision),
            self.store.fts_top(query, self.leg_k, revision),
        )
        rows, best_sim, best_rrf = fuse(vec_rows, lex_rows, self.top_n)
        return RetrievalResult(
            chunks=[Chunk.model_validate(r) for r in rows], best_sim=best_sim, best_rrf=best_rrf
        )

    async def steps_for(self, doc_id: str, revision: str | None):
        from ..schemas import Step

        return [Step(**step_from_row(r)) for r in await self.store.steps_for(doc_id, revision)]
