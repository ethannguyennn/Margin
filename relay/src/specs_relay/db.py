"""The only module that opens database connections or executes project SQL.

Settings come from Part 3's config.get_settings(). Tests may inject settings.
Rows are converted to Part 3's Chunk/Step models at the public boundary.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import logging
import math
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from psycopg import Rollback, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

if TYPE_CHECKING:
    from .schemas import Chunk, Step, MaterialText, ProcedureDraft, DraftStep, DiagramSpec, ProgressEvent

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


_CHUNK_COLUMNS = """c.chunk_id, c.doc_id, c.revision, c.section, d.title,
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
    return [Chunk(**row, sim=row["score"]) for row in await _vector_rows(q_embedding, k, revision)]


async def _fts_rows(query: str, k: int = 20, revision: str | None = None) -> list[dict]:
    limit = _limit(k)
    if not query.strip():
        return []
    clause, params = _revision_clause(revision)
    return await _rows(
        f"""SELECT {_CHUNK_COLUMNS}, ts_rank_cd(c.tsv, q.term) AS score
        FROM chunks c JOIN documents d USING (doc_id, revision)
        CROSS JOIN LATERAL (
            SELECT replace(websearch_to_tsquery('english', %s)::text, ' & ', ' | ')::tsquery AS term
        ) AS q
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
        f"""SELECT {_CHUNK_COLUMNS}, c.glance, c.body, c.warning, c.checkpoint,
        CASE WHEN g.approved THEN jsonb_build_object(
            'diagram_id', g.diagram_id, 'width', 576, 'height', 144, 'alt', g.spec->>'alt') END AS diagram
        FROM chunks c JOIN documents d USING (doc_id, revision)
        LEFT JOIN diagrams g ON g.diagram_id = c.diagram_id
            AND g.doc_id = c.doc_id AND g.revision = c.revision AND g.step_label = c.section
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


def seed_module():
    """Entry point expected by Part 3's authenticated /v1/ingest route.

    Resolve the owned seed module relative to this checkout, not the server's
    working directory. The relay image must include the root db/ and corpus/.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("_specs_corpus_seed", ROOT / "db/seed.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("The relay image must include db/seed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def ingest_corpus(corpus_dir: str | Path | None = None) -> list[dict]:
    return await seed_module().ingest(Path(corpus_dir) if corpus_dir else ROOT / "corpus")


async def list_procedures() -> list[dict]:
    return await _rows(
        """SELECT doc_id, title, revision, status FROM documents
        WHERE status = 'effective' ORDER BY doc_id"""
    )


async def write_event(session_id, trace_id, intent, outcome, doc_ids, transcript, latency_ms,
                      assignment_id: str | None = None) -> None:
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
                    (session_id, trace_id, intent, outcome, doc_ids, assignment_id, transcript, latency_ms)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (session_id, trace_id, intent, outcome, list(doc_ids or []), assignment_id, transcript,
                     Jsonb(metrics)),
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
        WHERE CASE WHEN jsonb_typeof(value) = 'number' THEN value::double precision > 0 ELSE false END
        GROUP BY stage ORDER BY stage"""
    )


async def validate_capabilities() -> dict:
    """Exercise vector + HNSW + Timescale on the configured service, then roll back.

    Uses a unique probe schema. No application tables or data are touched.
    Success is runtime evidence on that endpoint, not a claim about its billing tier.
    """
    if _embed_dim is None:
        raise RuntimeError("Call init_pool before checking capabilities")
    schema = "specs_probe_" + uuid4().hex
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
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('specs:migrate', 0))")
            cursor = await conn.execute(
                """SELECT format_type(atttypid, atttypmod) AS type FROM pg_attribute
                WHERE attrelid = to_regclass('chunks') AND attname = 'embedding' AND NOT attisdropped""")
            row = await cursor.fetchone()
            if row and row["type"] != f"vector({_embed_dim})":
                raise ValueError("Existing chunks vector dimension differs from EMBED_DIM; explicit migration required")
            await conn.execute(render_migration(_embed_dim), prepare=False)
            await conn.execute((ROOT / "db/migrations/002_v2.sql").read_text(encoding="utf-8"), prepare=False)


async def storage_counts() -> dict:
    """Non-secret row counts for migration evidence, including absent tables."""
    counts = {}
    for table in ("documents", "chunks", "sessions", "events", "deviations", "materials",
                  "drafts", "diagrams", "devices", "assignments", "progress"):
        exists = await _rows("SELECT to_regclass(%s) IS NOT NULL AS present", (table,))
        if exists[0]["present"]:
            rows = await _rows(sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(table)))
            counts[table] = rows[0]["n"]
        else:
            counts[table] = None
    return counts


async def upsert_corpus(documents: list[dict], chunks: list[dict]) -> list[dict]:
    """Atomic corpus replacement per supplied revision, including removed sections."""
    # Validate every vector before the first mutation.
    vectors = {chunk["chunk_id"]: vector_literal(chunk["embedding"]) for chunk in chunks}
    async with pool().connection() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('specs:seed', 0))")
            for doc in sorted(documents, key=lambda d: (d["doc_id"], d["revision"])):
                await _lock_document(conn, doc["doc_id"])
                cursor = await conn.execute(
                    "SELECT revision FROM drafts WHERE doc_id = %s AND approved_at IS NOT NULL", (doc["doc_id"],))
                published = {row["revision"] for row in await cursor.fetchall()}
                if doc["revision"] in published:
                    continue
                if published and doc["status"] == "effective":
                    # Re-seeding old markdown must not displace a portal revision.
                    doc = dict(doc, status="superseded")
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


# v2 authoring and device queries. Shared models are imported at their use sites
# so the v1 mock relay can boot before Part 3's v2 scaffold is merged.
MAX_FILE_BYTES = 20 * 1024 * 1024
_MATERIAL_COLUMNS = "material_id, created_at, filename, mime, sha256, doc_id, revision, title, status, error, material_text"
_DEVICE_COLUMNS = "device_id, pair_code, pair_expires, worker_name, claimed_at, created_at"


def _identifiers(doc_id: str, revision: str) -> None:
    if not re.fullmatch(r"[A-Z]{2,5}-\d{3}", doc_id) or not re.fullmatch(r"[A-Z0-9]{1,3}", revision):
        raise ValueError("Invalid document or revision identifier")


async def _next_id(sequence: str, prefix: str) -> str:
    # sequence is a module-owned constant, never interpolated into SQL.
    rows = await _rows("SELECT nextval(%s::regclass) AS value", (sequence,))
    return f"{prefix}-{rows[0]['value']:04d}"


async def _lock_document(conn, doc_id: str) -> None:
    await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("specs:publish:" + doc_id,))


async def _editable_draft(conn, doc_id: str, revision: str) -> dict:
    await _lock_document(conn, doc_id)
    cursor = await conn.execute(
        "SELECT * FROM drafts WHERE doc_id = %s AND revision = %s FOR UPDATE", (doc_id, revision))
    row = await cursor.fetchone()
    if row is None:
        raise LookupError("Draft was not found")
    if row["approved_at"] is not None:
        raise ValueError("Published revisions are immutable; upload a new revision")
    return row


async def insert_material(filename: str, mime: str, data: bytes, doc_id: str,
                          revision: str, title: str) -> str:
    _identifiers(doc_id, revision)
    if not isinstance(data, bytes) or not data or len(data) > MAX_FILE_BYTES:
        raise ValueError("Material must contain 1 byte to 20 MB")
    if not filename or not title.strip() or len(title) > 120:
        raise ValueError("Filename and title are required; title is limited to 120 characters")
    material_id = await _next_id("material_id_seq", "MAT")
    await _rows(
        """INSERT INTO materials(material_id, filename, mime, bytes, sha256, doc_id, revision, title, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'converting') RETURNING material_id""",
        (material_id, filename, mime, data, hashlib.sha256(data).hexdigest(), doc_id, revision, title))
    return material_id


async def set_material_status(material_id: str, status: str, error: str | None = None) -> None:
    if status not in {"converting", "ready", "failed", "approved"}:
        raise ValueError("Invalid material status")
    rows = await _rows(
        """UPDATE materials SET status = %s, error = %s WHERE material_id = %s
        AND (status <> 'approved' OR %s = 'approved') RETURNING material_id""",
        (status, error, material_id, status))
    if not rows:
        raise LookupError("Material not found or already published")


async def fail_interrupted_materials() -> int:
    rows = await _rows(
        """UPDATE materials SET status = 'failed', error = 'Conversion interrupted by relay restart. Upload again.'
        WHERE status = 'converting' RETURNING material_id""")
    return len(rows)


async def save_material_text(material_id: str, text: MaterialText) -> None:
    if text.material_id != material_id:
        raise ValueError("Material text belongs to a different upload")
    rows = await _rows(
        """UPDATE materials SET material_text = %s WHERE material_id = %s AND status <> 'approved'
        RETURNING material_id""", (Jsonb(text.model_dump(mode="json")), material_id))
    if not rows:
        raise LookupError("Material not found or already published")


async def get_material(material_id: str, *, include_bytes: bool = False) -> dict | None:
    columns = _MATERIAL_COLUMNS + (", bytes" if include_bytes else "")
    rows = await _rows(f"SELECT {columns} FROM materials WHERE material_id = %s", (material_id,))
    return rows[0] if rows else None


async def get_material_text(material_id: str) -> MaterialText | None:
    from .schemas import MaterialText
    row = await get_material(material_id)
    return MaterialText.model_validate(row["material_text"]) if row and row["material_text"] is not None else None


async def list_materials(*, query: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
    """Upload library metadata only; never transfer file bytes or extracted source text."""
    if not 1 <= limit <= 101 or offset < 0 or len(query) > 120:
        raise ValueError("Invalid material library query")
    return await _rows(
        """SELECT material_id, created_at, filename, mime, sha256, doc_id, revision,
        title, status, error, octet_length(bytes) AS size_bytes
        FROM materials
        WHERE strpos(lower(concat_ws(' ', doc_id, revision, title, filename)), lower(%s)) > 0
        ORDER BY created_at DESC, material_id DESC LIMIT %s OFFSET %s""",
        (query.strip(), limit, offset))


async def save_draft(draft: ProcedureDraft) -> None:
    _identifiers(draft.doc_id, draft.revision)
    async with pool().connection() as conn:
        async with conn.transaction():
            await _lock_document(conn, draft.doc_id)
            cursor = await conn.execute(
                """SELECT material_id FROM materials WHERE material_id = %s AND doc_id = %s
                AND revision = %s AND status <> 'approved' FOR UPDATE""",
                (draft.material_id, draft.doc_id, draft.revision))
            if await cursor.fetchone() is None:
                raise ValueError("Material does not belong to this editable draft")
            cursor = await conn.execute(
                """INSERT INTO drafts(doc_id, revision, material_id, title, steps, warnings)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (doc_id, revision) DO UPDATE SET material_id = EXCLUDED.material_id,
                title = EXCLUDED.title, steps = EXCLUDED.steps, warnings = EXCLUDED.warnings, updated_at = now()
                WHERE drafts.approved_at IS NULL RETURNING doc_id""",
                (draft.doc_id, draft.revision, draft.material_id, draft.title,
                 # Conversion is never a source of human diagram approval.
                 Jsonb([dict(s.model_dump(mode="json"), diagram_approved=False) for s in draft.steps]), Jsonb(draft.warnings)))
            if await cursor.fetchone() is None:
                raise ValueError("Published revisions are immutable")


async def get_draft(doc_id: str, revision: str) -> ProcedureDraft | None:
    from .schemas import ProcedureDraft
    rows = await _rows(
        """SELECT d.*, m.status FROM drafts d JOIN materials m USING (material_id)
        WHERE d.doc_id = %s AND d.revision = %s""", (doc_id, revision))
    if not rows:
        return None
    row = rows[0]
    return ProcedureDraft(doc_id=row["doc_id"], revision=row["revision"], material_id=row["material_id"],
                          title=row["title"], status="approved" if row["approved_at"] else row["status"],
                          steps=row["steps"], warnings=row["warnings"])


async def update_draft_step(doc_id: str, revision: str, label: str, step: DraftStep) -> None:
    if label != step.label:
        raise ValueError("Step labels cannot be renamed")
    async with pool().connection() as conn:
        async with conn.transaction():
            row = await _editable_draft(conn, doc_id, revision)
            steps = row["steps"]
            index = next((i for i, s in enumerate(steps) if s["label"] == label), None)
            if index is None:
                raise LookupError("Step was not found")
            value = step.model_dump(mode="json")
            previous = steps[index]
            # Editing a source or diagram invalidates the old human approval.
            diagram_changed = any(previous.get(k) != value.get(k) for k in ("diagram", "diagram_id", "quotes"))
            if value.get("diagram_id"):
                cursor = await conn.execute(
                    """SELECT spec, approved FROM diagrams WHERE diagram_id = %s AND doc_id = %s
                    AND revision = %s AND step_label = %s FOR UPDATE""",
                    (value["diagram_id"], doc_id, revision, label))
                diagram = await cursor.fetchone()
                if diagram is None or diagram["spec"] != value.get("diagram"):
                    raise ValueError("Diagram does not match this step; regenerate or detach it")
                value["diagram_approved"] = bool(diagram["approved"]) and not diagram_changed
                if diagram_changed:
                    await conn.execute("UPDATE diagrams SET approved = false WHERE diagram_id = %s",
                                       (value["diagram_id"],))
            else:
                value["diagram_approved"] = False
            steps[index] = value
            await conn.execute(
                "UPDATE drafts SET steps = %s, updated_at = now() WHERE doc_id = %s AND revision = %s",
                (Jsonb(steps), doc_id, revision))


async def save_diagram(doc_id: str, revision: str, label: str, spec: DiagramSpec,
                       tiles: list[bytes], preview: bytes) -> str:
    _identifiers(doc_id, revision)
    if not 1 <= len(tiles) <= 2 or any(not t or len(t) > MAX_FILE_BYTES for t in [*tiles, preview]):
        raise ValueError("Diagram needs 1-2 nonempty tiles and a preview, each at most 20 MB")
    diagram_id = await _next_id("diagram_id_seq", "DGM")
    await _rows(
        """INSERT INTO diagrams(diagram_id, doc_id, revision, step_label, spec, tiles, preview_png)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING diagram_id""",
        (diagram_id, doc_id, revision, label, Jsonb(spec.model_dump(mode="json")), tiles, preview))
    return diagram_id


async def approve_diagram(diagram_id: str) -> None:
    diagram = await get_diagram(diagram_id, approved_only=False)
    if diagram is None:
        raise LookupError("Diagram was not found")
    async with pool().connection() as conn:
        async with conn.transaction():
            row = await _editable_draft(conn, diagram["doc_id"], diagram["revision"])
            step = next((s for s in row["steps"] if s.get("diagram_id") == diagram_id), None)
            if step is None or step.get("diagram") != diagram["spec"]:
                raise ValueError("Diagram is not attached to this draft")
            if not step.get("verify", {}).get("ok"):
                raise ValueError("Verify the step before approving its diagram")
            step["diagram_approved"] = True
            await conn.execute("UPDATE diagrams SET approved = true WHERE diagram_id = %s", (diagram_id,))
            await conn.execute(
                "UPDATE drafts SET steps = %s, updated_at = now() WHERE doc_id = %s AND revision = %s",
                (Jsonb(row["steps"]), diagram["doc_id"], diagram["revision"]))


async def get_diagram(diagram_id: str, approved_only: bool = True) -> dict | None:
    # Superseded diagrams remain available to assignments pinned to that revision.
    # Auth/scope is the route owner's responsibility; unapproved bytes never pass this filter.
    clause = """AND g.approved AND (EXISTS (
        SELECT 1 FROM documents d WHERE d.doc_id = g.doc_id AND d.revision = g.revision AND d.status = 'effective')
        OR EXISTS (SELECT 1 FROM assignments a WHERE a.doc_id = g.doc_id AND a.revision = g.revision
        AND a.completed_at IS NULL))""" if approved_only else ""
    rows = await _rows(f"SELECT g.* FROM diagrams g WHERE g.diagram_id = %s {clause}", (diagram_id,))
    return rows[0] if rows else None


async def create_device(token_sha256: str, pair_code: str, expires: datetime) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", token_sha256):
        raise ValueError("Store a SHA-256 token hash, never the device token")
    if not re.fullmatch(r"[A-HJ-NP-Z2-9]{4}", pair_code) or expires.tzinfo is None:
        raise ValueError("Pair code or expiration is invalid")
    if expires <= datetime.now(timezone.utc):
        raise ValueError("Pair code has already expired")
    device_id = await _next_id("device_id_seq", "LNS")
    async with pool().connection() as conn:
        async with conn.transaction():
            await conn.execute("UPDATE devices SET pair_code = NULL WHERE claimed_at IS NULL AND pair_expires <= now()")
            await conn.execute(
                "INSERT INTO devices(device_id, token_sha256, pair_code, pair_expires) VALUES (%s, %s, %s, %s)",
                (device_id, token_sha256, pair_code, expires))
    return device_id


async def claim_device(pair_code: str, worker_name: str) -> dict | None:
    if not worker_name.strip() or len(worker_name) > 120:
        raise ValueError("Worker name must have 1-120 characters")
    rows = await _rows(
        f"""UPDATE devices SET worker_name = %s, claimed_at = now()
        WHERE pair_code = %s AND claimed_at IS NULL AND pair_expires > now() RETURNING {_DEVICE_COLUMNS}""",
        (worker_name.strip(), pair_code.strip().upper()))
    return rows[0] if rows else None


async def device_by_token(token_sha256: str) -> dict | None:
    rows = await _rows(f"SELECT {_DEVICE_COLUMNS} FROM devices WHERE token_sha256 = %s", (token_sha256,))
    return rows[0] if rows else None


async def list_devices() -> list[dict]:
    return await _rows(f"SELECT {_DEVICE_COLUMNS} FROM devices ORDER BY created_at, device_id")


async def create_assignment(device_id: str, doc_id: str, revision: str | None = None) -> str:
    assignment_id = await _next_id("assignment_id_seq", "ASN")
    clause, params = _revision_clause(revision)
    # Resolve and pin in the INSERT snapshot; later publication never rewrites assignments.
    rows = await _rows(
        f"""INSERT INTO assignments(assignment_id, device_id, doc_id, revision)
        SELECT %s, dev.device_id, d.doc_id, d.revision FROM documents d CROSS JOIN devices dev
        WHERE dev.device_id = %s AND dev.claimed_at IS NOT NULL AND d.doc_id = %s AND {clause}
        AND d.status IN ('effective', 'superseded')
        AND EXISTS (SELECT 1 FROM chunks c WHERE c.doc_id = d.doc_id AND c.revision = d.revision AND c.is_step)
        RETURNING assignment_id""", (assignment_id, device_id, doc_id, *params))
    if not rows:
        raise LookupError("Claimed device or published procedure was not found")
    return assignment_id


# A delivered task the lens never acted on (no progress) is handed out again after this
# long: the first response may have been lost on a Wi-Fi drop. Only within the lens's own
# 12 h assignment TTL, so a stale task the lens refuses cannot block newer ones.
REDELIVER_AFTER = "30 seconds"
LENS_ASSIGNMENT_TTL = "12 hours"


async def next_assignment(device_id: str) -> dict | None:
    rows = await _rows(
        f"""WITH pending AS (
            SELECT a.assignment_id FROM assignments a WHERE a.device_id = %s AND a.completed_at IS NULL
            AND (a.delivered_at IS NULL OR (a.delivered_at < now() - interval '{REDELIVER_AFTER}'
                 AND a.assigned_at > now() - interval '{LENS_ASSIGNMENT_TTL}'
                 AND NOT EXISTS (SELECT 1 FROM progress pr WHERE pr.assignment_id = a.assignment_id)))
            ORDER BY a.assigned_at, a.assignment_id FOR UPDATE SKIP LOCKED LIMIT 1
        ) UPDATE assignments a SET delivered_at = now() FROM pending p
        WHERE a.assignment_id = p.assignment_id RETURNING a.*""", (device_id,))
    return rows[0] if rows else None


def _timestamp(value) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Timestamps must include a timezone")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Timestamp must be Unix milliseconds")
    return datetime.fromtimestamp(value / 1000, timezone.utc)


async def insert_progress(events: list[ProgressEvent], *, device_id: str | None = None) -> int:
    """Bounded best-effort write, scoped to the authenticated device."""
    try:
        if not device_id:
            raise ValueError("An authenticated device_id is required for progress")
        if len(events) > 100:
            raise ValueError("Progress batches are limited to 100 events")
        accepted = 0
        async with asyncio.timeout(0.5):
            async with pool().connection() as conn:
                async with conn.transaction():
                    for event in events:
                        data = event if isinstance(event, dict) else event.model_dump()
                        cursor = await conn.execute(
                            """INSERT INTO progress(ts, assignment_id, step_id, kind)
                            SELECT %s, a.assignment_id, %s, %s FROM assignments a
                            WHERE a.assignment_id = %s AND a.device_id = %s
                            AND (%s::text IS NULL OR EXISTS (SELECT 1 FROM chunks c WHERE c.chunk_id = %s
                                AND c.doc_id = a.doc_id AND c.revision = a.revision AND c.is_step))
                            ON CONFLICT DO NOTHING RETURNING assignment_id""",
                            (_timestamp(data["ts"]), data["step_id"], data["kind"], data["assignment_id"],
                             device_id, data["step_id"], data["step_id"]))
                        inserted = await cursor.fetchone()
                        if inserted:
                            accepted += 1
                            if data["kind"] == "task_completed":
                                await conn.execute(
                                    """UPDATE assignments SET completed_at = coalesce(completed_at, %s)
                                    WHERE assignment_id = %s""", (_timestamp(data["ts"]), data["assignment_id"]))
        return accepted
    except Exception as exc:
        log.warning("Progress write skipped (%s)", type(exc).__name__)
        return 0


async def progress_board(since=None) -> list[dict]:
    # since filters changed rows, but the latest step and its duration always use
    # full history. Deviations still appear when there has been no progress write.
    return await _rows(
        """SELECT a.device_id, dev.worker_name, a.assignment_id, a.doc_id, a.revision, d.title,
        coalesce(c.step_order, 0) AS step_index,
        (SELECT count(*) FROM chunks s WHERE s.doc_id = a.doc_id AND s.revision = a.revision AND s.is_step) AS total,
        coalesce(p.kind, 'assigned') AS kind,
        extract(epoch FROM coalesce(p.ts, a.assigned_at)) * 1000 AS ts,
        extract(epoch FROM coalesce(started.ts, p.ts, a.assigned_at)) * 1000 AS step_started_at,
        coalesce(dv.items, '[]'::jsonb) AS deviations
        FROM assignments a JOIN devices dev USING (device_id)
        JOIN documents d ON d.doc_id = a.doc_id AND d.revision = a.revision
        LEFT JOIN LATERAL (SELECT * FROM progress WHERE assignment_id = a.assignment_id
            ORDER BY ts DESC, received_at DESC LIMIT 1) p ON true
        LEFT JOIN LATERAL (SELECT step_id FROM progress WHERE assignment_id = a.assignment_id
            AND step_id IS NOT NULL ORDER BY ts DESC, received_at DESC LIMIT 1) last_step ON true
        LEFT JOIN chunks c ON c.chunk_id = last_step.step_id
        LEFT JOIN LATERAL (SELECT max(ts) AS ts FROM progress WHERE assignment_id = a.assignment_id
            AND step_id = last_step.step_id AND kind = 'step_started' AND ts <= p.ts) started ON true
        LEFT JOIN LATERAL (SELECT jsonb_agg(jsonb_build_object(
            'deviation_id', v.deviation_id, 'text', v.text, 'ts', v.ts) ORDER BY v.ts) AS items, max(v.ts) AS last_ts
            FROM deviations v WHERE v.doc_id = a.doc_id AND v.ts >= a.assigned_at
            AND (v.step_id IS NULL OR v.step_id LIKE a.doc_id || ':' || a.revision || ':%')) dv ON true
        WHERE a.completed_at IS NULL
        AND (%s::timestamptz IS NULL OR greatest(a.assigned_at, p.received_at, dv.last_ts) >= %s)
        ORDER BY a.assigned_at DESC, a.assignment_id""",
        (None if since is None else _timestamp(since), None if since is None else _timestamp(since)))


async def approved_drafts() -> list[ProcedureDraft]:
    rows = await _rows("SELECT doc_id, revision FROM drafts WHERE approved_at IS NOT NULL ORDER BY approved_at, doc_id")
    return [draft for r in rows if (draft := await get_draft(r["doc_id"], r["revision"])) is not None]


async def publish_prepared(draft: ProcedureDraft, chunks: list[dict], material: MaterialText) -> dict:
    """Commit a previously verified/embedded snapshot, or reject a concurrent edit."""
    vectors = {c["chunk_id"]: vector_literal(c["embedding"]) for c in chunks}
    expected = [s.model_dump(mode="json") for s in draft.steps]
    async with pool().connection() as conn:
        async with conn.transaction():
            await _lock_document(conn, draft.doc_id)
            cursor = await conn.execute(
                "SELECT * FROM drafts WHERE doc_id = %s AND revision = %s FOR UPDATE",
                (draft.doc_id, draft.revision))
            stored = await cursor.fetchone()
            if stored is None:
                raise LookupError("Draft was not found")
            cursor = await conn.execute(
                "SELECT material_text, status FROM materials WHERE material_id = %s FOR UPDATE", (draft.material_id,))
            source = await cursor.fetchone()
            if source is None or source["material_text"] != material.model_dump(mode="json"):
                raise ValueError("Source material changed during publication; verify again")
            if source["status"] not in {"ready", "approved"}:
                raise ValueError("Source material is no longer ready for publication")
            if any(stored[k] != v for k, v in {
                "steps": expected, "warnings": draft.warnings, "title": draft.title, "material_id": draft.material_id
            }.items()):
                raise ValueError("Draft changed during publication; review and approve again")
            if stored["approved_at"]:
                cursor = await conn.execute(
                    "SELECT doc_id FROM documents WHERE doc_id = %s AND revision = %s", (draft.doc_id, draft.revision))
                if await cursor.fetchone():
                    return {"doc_id": draft.doc_id, "revision": draft.revision, "steps": len(draft.steps)}
            else:
                cursor = await conn.execute(
                    "SELECT status FROM documents WHERE doc_id = %s AND revision = %s", (draft.doc_id, draft.revision))
                existing = await cursor.fetchone()
                if existing is not None and existing["status"] != "draft":
                    raise ValueError("This revision is already published; upload a new revision")
            for step in draft.steps:
                if step.diagram is not None:
                    cursor = await conn.execute(
                        """SELECT diagram_id FROM diagrams WHERE diagram_id = %s AND doc_id = %s
                        AND revision = %s AND step_label = %s AND spec = %s AND approved FOR UPDATE""",
                        (step.diagram_id, draft.doc_id, draft.revision, step.label,
                         Jsonb(step.diagram.model_dump(mode="json"))))
                    if await cursor.fetchone() is None:
                        raise ValueError(f"Step {step.label}: diagram is not approved")
            await conn.execute(
                "UPDATE documents SET status = 'superseded' WHERE doc_id = %s AND status = 'effective'",
                (draft.doc_id,))
            await conn.execute(
                """INSERT INTO documents(doc_id, revision, title, status, effective_date)
                VALUES (%s, %s, %s, 'effective', CURRENT_DATE)
                ON CONFLICT (doc_id, revision) DO UPDATE SET title = EXCLUDED.title,
                status = 'effective', effective_date = EXCLUDED.effective_date""",
                (draft.doc_id, draft.revision, draft.title))
            await conn.execute(
                "UPDATE chunks SET is_step = false, step_order = NULL WHERE doc_id = %s AND revision = %s",
                (draft.doc_id, draft.revision))
            for chunk in chunks:
                await conn.execute(
                    """INSERT INTO chunks(chunk_id, doc_id, revision, section, is_step, step_order, heading,
                    text, embedding, glance, body, warning, checkpoint, diagram_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, %s, %s, %s, %s)
                    ON CONFLICT (chunk_id) DO UPDATE SET is_step = EXCLUDED.is_step,
                    step_order = EXCLUDED.step_order, heading = EXCLUDED.heading, text = EXCLUDED.text,
                    embedding = EXCLUDED.embedding, glance = EXCLUDED.glance, body = EXCLUDED.body,
                    warning = EXCLUDED.warning, checkpoint = EXCLUDED.checkpoint, diagram_id = EXCLUDED.diagram_id""",
                    (*[chunk[k] for k in ("chunk_id", "doc_id", "revision", "section", "is_step", "step_order", "heading", "text")],
                     vectors[chunk["chunk_id"]], *[chunk.get(k) for k in ("glance", "body", "warning", "checkpoint", "diagram_id")]))
            await conn.execute(
                "DELETE FROM chunks WHERE doc_id = %s AND revision = %s AND NOT (chunk_id = ANY(%s))",
                (draft.doc_id, draft.revision, list(vectors)))
            await conn.execute(
                "UPDATE drafts SET approved_at = coalesce(approved_at, now()) WHERE doc_id = %s AND revision = %s",
                (draft.doc_id, draft.revision))
            await conn.execute("UPDATE materials SET status = 'approved', error = NULL WHERE material_id = %s",
                               (draft.material_id,))
    return {"doc_id": draft.doc_id, "revision": draft.revision, "steps": len(draft.steps)}


async def validate_v2_migration() -> dict:
    """Apply 001/002 twice to synthetic rows in a disposable schema, then roll back.

    Opt-in Tiger evidence, never an implicit startup task. Existing application
    rows are outside this schema; the returned counts refer only to the probe.
    """
    if _embed_dim is None:
        raise RuntimeError('Call init_pool before the v2 migration probe')
    schema = 'specs_v2_probe_' + uuid4().hex
    report = {'schema': schema, 'rolled_back': True}
    async with pool().connection() as conn:
        async with conn.transaction():
            await conn.execute('CREATE EXTENSION IF NOT EXISTS vector')
            await conn.execute('CREATE EXTENSION IF NOT EXISTS timescaledb')
            await conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
            await conn.execute(sql.SQL('SET LOCAL search_path TO {}, public').format(sql.Identifier(schema)))
            await conn.execute(render_migration(_embed_dim), prepare=False)
            await conn.execute("INSERT INTO documents VALUES ('TST-999', 'A', 'Synthetic migration probe', 'effective', CURRENT_DATE)")
            await conn.execute(
                """INSERT INTO chunks(chunk_id, doc_id, revision, section, is_step, step_order, heading, text, embedding)
                VALUES ('TST-999:A:1', 'TST-999', 'A', '1', true, 1, 'Isolate power', 'Isolate power.', %s::vector)""",
                (vector_literal([1.0] + [0.0] * (_embed_dim - 1)),))
            async def counts():
                cursor = await conn.execute('SELECT (SELECT count(*) FROM documents) AS documents, (SELECT count(*) FROM chunks) AS chunks')
                return await cursor.fetchone()
            report['before'] = await counts()
            migration = (ROOT / 'db/migrations/002_v2.sql').read_text(encoding='utf-8')
            for key in ('after_first', 'after_second'):
                await conn.execute(migration, prepare=False)
                report[key] = await counts()
            await conn.execute("INSERT INTO devices(device_id, token_sha256) VALUES ('LNS-probe', 'synthetic-hash')")
            await conn.execute("INSERT INTO assignments(assignment_id, device_id, doc_id, revision) VALUES ('ASN-probe', 'LNS-probe', 'TST-999', 'A')")
            for step_id, kind in ((None, 'task_started'), ('TST-999:A:1', 'step_started')):
                for _ in range(2):
                    await conn.execute(
                        """INSERT INTO progress(ts, assignment_id, step_id, kind)
                        VALUES ('2026-01-01T00:00:00Z', 'ASN-probe', %s, %s) ON CONFLICT DO NOTHING""",
                        (step_id, kind))
            cursor = await conn.execute('SELECT count(*) AS rows, count(*) FILTER (WHERE step_id IS NULL) AS task_rows FROM progress')
            report['progress'] = await cursor.fetchone()
            cursor = await conn.execute(
                """SELECT indexdef FROM pg_indexes WHERE schemaname = %s AND indexname = 'progress_idempotency'""", (schema,))
            report['unique_index'] = (await cursor.fetchone())['indexdef']
            cursor = await conn.execute(
                """SELECT count(*) AS n FROM timescaledb_information.hypertables
                WHERE hypertable_schema = %s AND hypertable_name = 'progress'""", (schema,))
            report['progress_hypertable'] = (await cursor.fetchone())['n'] == 1
            if not (report['before'] == report['after_first'] == report['after_second']
                    and report['progress'] == {'rows': 2, 'task_rows': 1} and report['progress_hypertable']):
                raise RuntimeError('V2 migration or progress uniqueness probe failed')
            raise Rollback()
    return report
