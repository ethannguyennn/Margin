"""The only module that opens database connections or executes project SQL.

Settings come from Part 3's config.get_settings(). Tests may inject settings.
Rows are converted to Part 3's Chunk/Step models at the public boundary.
"""
from __future__ import annotations

import asyncio
import logging
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from psycopg import Rollback, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

if TYPE_CHECKING:
    from .schemas import Chunk, Step

log = logging.getLogger(__name__)
_pool: AsyncConnectionPool | None = None
_embed_dim: int | None = None
_init_lock = asyncio.Lock()
ROOT = Path(__file__).resolve().parents[3]


def get_settings():
    from .config import get_settings as load_settings
    return load_settings()


def setting(settings, name: str):
    """Accept conventional lower-case or env-style Part 3 setting attributes."""
    return getattr(settings, name.lower()) if hasattr(settings, name.lower()) else getattr(settings, name)


def embedding_dimension(value: Any) -> int:
    # vector HNSW supports up to 2,000 dimensions; reject truncation/bools.
    if isinstance(value, bool) or str(value) != str(int(value)) or not 1 <= int(value) <= 2000:
        raise ValueError("EMBED_DIM must be an integer between 1 and 2000 for vector HNSW")
    return int(value)


async def init_pool(settings=None) -> None:
    global _pool, _embed_dim
    async with _init_lock:
        if _pool is not None and not _pool.closed:
            return
        settings = settings if settings is not None else get_settings()
        dimension = embedding_dimension(setting(settings, "EMBED_DIM"))
        url = setting(settings, "DATABASE_URL")
        if hasattr(url, "get_secret_value"):
            url = url.get_secret_value()
        if not url:
            raise ValueError("DATABASE_URL is required in Part 3 config")
        pool = AsyncConnectionPool(
            str(url), open=False, min_size=1, max_size=5, timeout=5,
            kwargs={"row_factory": dict_row, "connect_timeout": 10},
        )
        try:
            await pool.open(wait=True, timeout=10)
        except BaseException:
            await pool.close()
            raise
        _pool, _embed_dim = pool, dimension


async def close_pool() -> None:
    global _pool, _embed_dim
    if _pool is not None:
        await _pool.close()
    _pool, _embed_dim = None, None


def pool() -> AsyncConnectionPool:
    if _pool is None or _pool.closed:
        raise RuntimeError("Call init_pool before database operations")
    return _pool


async def _rows(query, params=()) -> list[dict]:
    async with pool().connection() as conn:
        cursor = await conn.execute(query, params)
        return await cursor.fetchall()


async def ping() -> str:
    try:
        async with asyncio.timeout(2):
            await _rows("SELECT 1")
        return "ok"
    except Exception:
        return "down"


def vector_literal(values, dimension: int | None = None) -> str:
    dimension = dimension if dimension is not None else _embed_dim
    numbers = [float(value) for value in values]
    if dimension is None or len(numbers) != dimension:
        raise ValueError("Embedding length does not match configured EMBED_DIM")
    if not all(math.isfinite(number) for number in numbers) or not any(numbers):
        raise ValueError("Embedding must contain finite numbers and have nonzero norm")
    return "[" + ",".join(str(number) for number in numbers) + "]"


def _limit(k: int) -> int:
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= 100:
        raise ValueError("k must be an integer between 1 and 100")
    return k


def _revision_clause(revision: str | None) -> tuple[str, tuple]:
    if revision is None:
        return "d.status = 'effective'", ()
    if not revision or ":" in revision:
        raise ValueError("revision must be a nonempty revision identifier")
    return "d.revision = %s", (revision,)


_CHUNK_COLUMNS = """c.chunk_id, c.doc_id, c.revision, c.section,
    c.is_step, c.step_order, c.heading, c.text"""


async def _vector_rows(q_embedding, k: int = 20, revision: str | None = None) -> list[dict]:
    vector = vector_literal(q_embedding)
    clause, params = _revision_clause(revision)
    return await _rows(
        f"""SELECT {_CHUNK_COLUMNS}, 1 - (c.embedding <=> %s::vector) AS score
        FROM chunks c JOIN documents d USING (doc_id, revision)
        WHERE {clause}
        ORDER BY c.embedding <=> %s::vector LIMIT %s""",
        (vector, *params, vector, _limit(k)),
    )


async def vector_top(q_embedding, k: int = 20, revision: str | None = None) -> list[Chunk]:
    from .schemas import Chunk
    return [Chunk(**row) for row in await _vector_rows(q_embedding, k, revision)]


async def _fts_rows(query: str, k: int = 20, revision: str | None = None) -> list[dict]:
    limit = _limit(k)
    if not query.strip():
        return []
    clause, params = _revision_clause(revision)
    return await _rows(
        f"""SELECT {_CHUNK_COLUMNS}, ts_rank_cd(c.tsv, q.term) AS score
        FROM chunks c JOIN documents d USING (doc_id, revision)
        CROSS JOIN websearch_to_tsquery('english', %s) AS q(term)
        WHERE {clause} AND c.tsv @@ q.term
        ORDER BY score DESC, c.chunk_id LIMIT %s""",
        (query, *params, limit),
    )


async def fts_top(query: str, k: int = 20, revision: str | None = None) -> list[Chunk]:
    from .schemas import Chunk
    return [Chunk(**row) for row in await _fts_rows(query, k, revision)]


async def document_for(doc_id: str, revision: str | None = None) -> dict | None:
    clause, params = _revision_clause(revision)
    rows = await _rows(
        f"""SELECT d.doc_id, d.revision, d.title, d.status
        FROM documents d WHERE d.doc_id = %s AND {clause}""",
        (doc_id, *params),
    )
    return rows[0] if rows else None


async def _step_rows(doc_id: str, revision: str | None = None) -> list[dict]:
    clause, params = _revision_clause(revision)
    return await _rows(
        f"""SELECT {_CHUNK_COLUMNS}
        FROM chunks c JOIN documents d USING (doc_id, revision)
        WHERE c.doc_id = %s AND {clause} AND c.is_step
        ORDER BY c.step_order, c.chunk_id""",
        (doc_id, *params),
    )


async def steps_for(doc_id: str, revision: str | None = None) -> list[Step]:
    from .walkthrough import step_from_chunk
    return [step_from_chunk(row) for row in await _step_rows(doc_id, revision)]


class RetrievalStore:
    """Part 4's raw-row Store protocol, using only this module's pool/SQL.

    Wire Retriever(RetrievalStore(), embedder), rather than Retriever.from_pool.
    The public steps_for above remains the frozen list[Step] interface.
    """
    vector_top = staticmethod(_vector_rows)
    fts_top = staticmethod(_fts_rows)
    steps_for = staticmethod(_step_rows)


async def list_procedures() -> list[dict]:
    return await _rows(
        """SELECT doc_id, title, revision, status FROM documents
        WHERE status = 'effective' ORDER BY doc_id"""
    )


async def write_event(session_id, trace_id, intent, outcome, doc_ids, transcript, latency_ms) -> None:
    """Best effort, bounded analytics; a broken database never breaks an answer."""
    try:
        # Neither raw audio nor arbitrary request objects are accepted.
        if not isinstance(transcript, (str, type(None))):
            raise TypeError("transcript must be text")
        metrics = dict(latency_ms)
        if any(isinstance(v, bool) or not isinstance(v, (int, float))
               or not math.isfinite(v) or v < 0 for v in metrics.values()):
            raise ValueError("latency_ms values must be nonnegative finite numbers")
        async with asyncio.timeout(0.5):
            async with pool().connection() as conn:
                await conn.execute(
                    """INSERT INTO events
                    (session_id, trace_id, intent, outcome, doc_ids, transcript, latency_ms)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                    (session_id, trace_id, intent, outcome, list(doc_ids or []), transcript, Jsonb(metrics)),
                )
    except Exception as exc:
        # Exception messages can contain a DSN or transcript. Log only the class.
        log.warning("Analytics write skipped (%s)", type(exc).__name__)


async def next_deviation_id() -> str:
    rows = await _rows("SELECT nextval('deviation_id_seq') AS value")
    return f"DEV-{rows[0]['value']:04d}"


async def insert_deviation(deviation_id: str, session_id, doc_id: str | None,
                           step_id: str | None, text: str, notified: bool = False) -> None:
    if not text.strip():
        raise ValueError("Deviation text must not be blank")
    async with pool().connection() as conn:
        await conn.execute(
            """INSERT INTO deviations (deviation_id, session_id, doc_id, step_id, text, notified)
            VALUES (%s, %s, %s, %s, %s, %s)""",
            (deviation_id, session_id, doc_id, step_id, text, notified),
        )


async def set_deviation_notified(deviation_id: str, notified: bool) -> None:
    async with pool().connection() as conn:
        cursor = await conn.execute(
            "UPDATE deviations SET notified = %s WHERE deviation_id = %s",
            (notified, deviation_id),
        )
        if cursor.rowcount != 1:
            raise LookupError("Deviation does not exist")


async def latency_summary() -> list[dict]:
    """Part 3's make latency can call this; no second connection owner needed."""
    return await _rows(
        """SELECT stage, count(*) AS samples,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY value::double precision) AS p50_ms,
        percentile_cont(0.95) WITHIN GROUP (ORDER BY value::double precision) AS p95_ms
        FROM events CROSS JOIN LATERAL jsonb_each(latency_ms) AS metric(stage, value)
        WHERE jsonb_typeof(value) = 'number'
        GROUP BY stage ORDER BY stage"""
    )


async def validate_capabilities() -> dict:
    """Exercise vector + HNSW + Timescale on the configured service, then roll back.

    Uses a unique probe schema. No application tables or data are touched.
    Success is runtime evidence on that endpoint, not a claim about its billing tier.
    """
    if _embed_dim is None:
        raise RuntimeError("Call init_pool before checking capabilities")
    schema = "margin_probe_" + uuid4().hex
    report = {}
    async with pool().connection() as conn:
        async with conn.transaction():
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
            await conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            await conn.execute(sql.SQL("CREATE TABLE {}.vectors (v vector({}))").format(
                sql.Identifier(schema), sql.Literal(_embed_dim)))
            await conn.execute(sql.SQL(
                "CREATE INDEX probe_hnsw ON {}.vectors USING hnsw (v vector_cosine_ops)"
            ).format(sql.Identifier(schema)))
            vector = vector_literal([1.0] + [0.0] * (_embed_dim - 1))
            await conn.execute(sql.SQL("INSERT INTO {}.vectors VALUES (%s::vector)").format(
                sql.Identifier(schema)), (vector,))
            cursor = await conn.execute(sql.SQL(
                "SELECT v <=> %s::vector AS distance FROM {}.vectors ORDER BY v <=> %s::vector"
            ).format(sql.Identifier(schema)), (vector, vector))
            if (await cursor.fetchone())["distance"] != 0:
                raise RuntimeError("Vector cosine probe failed")
            await conn.execute(sql.SQL("CREATE TABLE {}.events (ts timestamptz NOT NULL)").format(
                sql.Identifier(schema)))
            await conn.execute("SELECT create_hypertable(%s::regclass, 'ts')", (f"{schema}.events",))
            cursor = await conn.execute(
                """SELECT count(*) AS n FROM timescaledb_information.hypertables
                WHERE hypertable_schema = %s AND hypertable_name = 'events'""", (schema,))
            if (await cursor.fetchone())["n"] != 1:
                raise RuntimeError("Timescale hypertable probe failed")
            cursor = await conn.execute(
                "SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector', 'timescaledb')")
            report = {row["extname"]: row["extversion"] for row in await cursor.fetchall()}
            report.update(hnsw=True, create_hypertable=True, embed_dim=_embed_dim)
            raise Rollback()
    return report


def render_migration(dimension: int) -> str:
    dimension = embedding_dimension(dimension)
    return (ROOT / "db/migrations/001_init.sql").read_text(encoding="utf-8").replace(
        "{{EMBED_DIM}}", str(dimension))


async def apply_migrations() -> None:
    if _embed_dim is None:
        raise RuntimeError("Call init_pool before migrating")
    async with pool().connection() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('margin:migrate', 0))")
            cursor = await conn.execute(
                """SELECT format_type(atttypid, atttypmod) AS type FROM pg_attribute
                WHERE attrelid = to_regclass('chunks') AND attname = 'embedding' AND NOT attisdropped""")
            row = await cursor.fetchone()
            if row and row["type"] != f"vector({_embed_dim})":
                raise ValueError("Existing chunks vector dimension differs from EMBED_DIM; explicit migration required")
            await conn.execute(render_migration(_embed_dim), prepare=False)


async def upsert_corpus(documents: list[dict], chunks: list[dict]) -> list[dict]:
    """Atomic corpus replacement per supplied revision, including removed sections."""
    # Validate every vector before the first mutation.
    vectors = {chunk["chunk_id"]: vector_literal(chunk["embedding"]) for chunk in chunks}
    async with pool().connection() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('margin:seed', 0))")
            for doc in documents:
                await conn.execute(
                    """INSERT INTO documents (doc_id, revision, title, status, effective_date)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (doc_id, revision) DO UPDATE SET
                    title = EXCLUDED.title, status = EXCLUDED.status, effective_date = EXCLUDED.effective_date""",
                    tuple(doc[key] for key in ("doc_id", "revision", "title", "status", "effective_date")),
                )
                doc_chunks = [c for c in chunks if (c["doc_id"], c["revision"]) == (doc["doc_id"], doc["revision"])]
                if not doc_chunks:
                    raise ValueError("Cannot seed an empty document")
                # Clear step order before upserting so reordering does not conflict
                # with the unique per-revision index midway through the transaction.
                await conn.execute(
                    "UPDATE chunks SET is_step = false, step_order = NULL WHERE doc_id = %s AND revision = %s",
                    (doc["doc_id"], doc["revision"]),
                )
                for chunk in doc_chunks:
                    await conn.execute(
                        """INSERT INTO chunks
                        (chunk_id, doc_id, revision, section, is_step, step_order, heading, text, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                        ON CONFLICT (chunk_id) DO UPDATE SET
                        is_step = EXCLUDED.is_step, step_order = EXCLUDED.step_order,
                        heading = EXCLUDED.heading, text = EXCLUDED.text, embedding = EXCLUDED.embedding""",
                        (*tuple(chunk[key] for key in ("chunk_id", "doc_id", "revision", "section",
                                                       "is_step", "step_order", "heading", "text")),
                         vectors[chunk["chunk_id"]]),
                    )
                await conn.execute(
                    """DELETE FROM chunks WHERE doc_id = %s AND revision = %s
                    AND NOT (chunk_id = ANY(%s))""",
                    (doc["doc_id"], doc["revision"], [c["chunk_id"] for c in doc_chunks]),
                )
            cursor = await conn.execute(
                """SELECT doc_id, revision, count(*) AS chunks,
                count(*) FILTER (WHERE is_step) AS steps FROM chunks
                GROUP BY doc_id, revision ORDER BY doc_id, revision""")
            return await cursor.fetchall()
