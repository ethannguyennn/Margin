import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from part5_support import RecordingConnection, RecordingPool, schema_dependencies
from margin_relay import db
from db.seed import load_corpus


@pytest.mark.parametrize("value", [0, -1, 2001, True, 1.5, "768; DROP TABLE chunks"])
def test_bad_dimensions_are_rejected(value):
    with pytest.raises((ValueError, TypeError)):
        db.embedding_dimension(value)


def test_migration_uses_config_dimension_and_all_three_indexes():
    text = db.render_migration(1536)
    assert "vector(1536)" in text and "{{EMBED_DIM}}" not in text and "vector(768)" not in text
    assert "USING hnsw" in text and "USING gin" in text
    assert "create_hypertable('events', 'ts'" in text
    assert "CREATE SEQUENCE IF NOT EXISTS deviation_id_seq" in text


@pytest.mark.parametrize("values", [[0, 0], [1], [float("inf"), 0], [float("nan"), 1]])
def test_invalid_vectors_fail_before_querying(values):
    with pytest.raises(ValueError):
        db.vector_literal(values, 2)


@pytest.mark.asyncio
async def test_pool_opens_once_and_closes(monkeypatch):
    instance = RecordingPool()
    instance.open = AsyncMock()
    calls = []

    def factory(*args, **kwargs):
        calls.append((args, kwargs))
        return instance

    monkeypatch.setattr(db, "_pool", None)
    monkeypatch.setattr(db, "_embed_dim", None)
    monkeypatch.setattr(db, "AsyncConnectionPool", factory)
    settings = SimpleNamespace(database_url="fixture-dsn", embed_dim=768)
    await db.init_pool(settings)
    await db.init_pool(settings)
    assert len(calls) == 1 and calls[0][1]["open"] is False
    instance.open.assert_awaited_once()
    await db.close_pool()
    assert instance.closed and db._pool is None


@pytest.mark.asyncio
async def test_failed_pool_initialization_is_not_published(monkeypatch):
    instance = RecordingPool()
    instance.open = AsyncMock(side_effect=RuntimeError("unreachable"))
    monkeypatch.setattr(db, "_pool", None)
    monkeypatch.setattr(db, "AsyncConnectionPool", lambda *a, **k: instance)
    with pytest.raises(RuntimeError):
        await db.init_pool(SimpleNamespace(database_url="fixture-dsn", embed_dim=768))
    assert instance.closed and db._pool is None


@pytest.mark.asyncio
@pytest.mark.parametrize("revision", [None, "D"])
async def test_retrieval_has_effective_or_explicit_revision_filter(monkeypatch, schema_dependencies, revision):
    calls = []
    row = {"chunk_id": "SOP-114:C:4.2", "doc_id": "SOP-114", "revision": "C",
           "section": "4.2", "text": "Torque to 4 N-m.", "score": 0.9}

    async def rows(query, params=()):
        calls.append((query, params))
        return [row]

    monkeypatch.setattr(db, "_rows", rows)
    monkeypatch.setattr(db, "_embed_dim", 2)
    vector = await db.vector_top([1.0, 0.0], 20, revision)
    lexical = await db.fts_top("M5'); DROP TABLE chunks; --", 20, revision)
    assert vector[0].chunk_id == lexical[0].chunk_id
    for query, params in calls:
        assert ("d.status = 'effective'" in query) == (revision is None)
        assert ("d.revision = %s" in query) == (revision is not None)
        if revision:
            assert revision in params
        assert "DROP TABLE" not in query
    assert "<=> %s::vector" in calls[0][0]
    assert "@@ q.term" in calls[1][0]
    assert "DROP TABLE" in calls[1][1][0]


@pytest.mark.asyncio
async def test_steps_select_only_procedural_chunks_in_order(monkeypatch, schema_dependencies):
    _, chunks = load_corpus()
    expected = [c for c in chunks if c["doc_id"] == "SOP-114" and c["revision"] == "C" and c["is_step"]]
    rows = AsyncMock(return_value=expected)
    monkeypatch.setattr(db, "_rows", rows)
    steps = await db.steps_for("SOP-114", None)
    query, params = rows.await_args.args
    assert "AND c.is_step" in query and "ORDER BY c.step_order" in query
    assert params == ("SOP-114",)
    assert [s.label for s in steps] == [f"4.{i}" for i in range(1, 8)]


@pytest.mark.asyncio
async def test_retrieval_adapter_keeps_raw_text_section_and_score(monkeypatch):
    _, chunks = load_corpus()
    raw = next(c for c in chunks if c["chunk_id"] == "SOP-114:C:4.2") | {"score": 0.91}
    monkeypatch.setattr(db, "_rows", AsyncMock(return_value=[raw]))
    monkeypatch.setattr(db, "_embed_dim", 2)
    store = db.RetrievalStore()
    assert (await store.vector_top([1, 0], 20, None))[0]["score"] == 0.91
    assert (await store.fts_top("M5 bracket", 20, None))[0]["text"] == raw["text"]
    assert (await store.steps_for("SOP-114", None))[0]["section"] == "4.2"


@pytest.mark.asyncio
async def test_event_writes_latency_json_without_audio(monkeypatch):
    pool = RecordingPool()
    monkeypatch.setattr(db, "_pool", pool)
    await db.write_event(None, "trace-fixture", "question", "answered", ["SOP-114"],
                        "M5 torque", {"stt": 0, "total": 12.5})
    query, params, _ = pool.conn.calls[0]
    assert "INSERT INTO events" in query and "latency_ms" in query
    assert params[-1].obj == {"stt": 0, "total": 12.5}
    assert params[-2] == "M5 torque" and "audio" not in query
    assert pool.conn.committed


@pytest.mark.asyncio
async def test_event_failure_is_swallowed_with_monkeypatched_dead_pool(monkeypatch, caplog):
    class DeadPool:
        closed = False

        def connection(self):
            raise RuntimeError("sensitive connection information must not be logged")

    monkeypatch.setattr(db, "_pool", DeadPool())
    await db.write_event(None, "trace", "question", "answered", [], "text", {"total": 1})
    assert "Analytics write skipped (RuntimeError)" in caplog.text
    assert "sensitive connection" not in caplog.text
    assert await db.ping() == "down"


@pytest.mark.asyncio
async def test_event_timeout_cannot_hold_answer_indefinitely(monkeypatch):
    connection = RecordingConnection()

    async def hang(*args, **kwargs):
        await asyncio.sleep(10)

    connection.execute = hang
    monkeypatch.setattr(db, "_pool", RecordingPool(connection))
    async with asyncio.timeout(1.5):
        await db.write_event(None, "trace", "question", "answered", [], "text", {"total": 1})
    assert connection.rolled_back


@pytest.mark.asyncio
async def test_event_rejects_binary_transcript_and_nonfinite_latency(monkeypatch):
    pool = RecordingPool()
    monkeypatch.setattr(db, "_pool", pool)
    await db.write_event(None, "", "", "", [], b"raw audio", {"total": 1})
    await db.write_event(None, "", "", "", [], "text", {"total": float("nan")})
    assert pool.checkouts == 0


@pytest.mark.asyncio
async def test_sequence_ids_expand_without_wrapping(monkeypatch):
    rows = AsyncMock(return_value=[{"value": 10000}])
    monkeypatch.setattr(db, "_rows", rows)
    assert await db.next_deviation_id() == "DEV-10000"
    assert "nextval" in rows.await_args.args[0]


@pytest.mark.asyncio
async def test_latency_reads_events_instead_of_a_separate_store(monkeypatch):
    rows = AsyncMock(return_value=[])
    monkeypatch.setattr(db, "_rows", rows)
    await db.latency_summary()
    query = rows.await_args.args[0]
    assert "FROM events" in query and "jsonb_each(latency_ms)" in query
    assert "percentile_cont(0.5)" in query and "percentile_cont(0.95)" in query


@pytest.mark.asyncio
async def test_corpus_upsert_commits_once_and_removes_stale_sections(monkeypatch):
    documents, chunks = load_corpus()
    chunks = [dict(c, embedding=[1, 0]) for c in chunks]
    pool = RecordingPool()
    monkeypatch.setattr(db, "_pool", pool)
    monkeypatch.setattr(db, "_embed_dim", 2)
    await db.upsert_corpus(documents, chunks)
    assert pool.checkouts == 1 and pool.conn.committed
    calls = pool.conn.calls
    assert sum("ON CONFLICT (doc_id, revision)" in q for q, _, _ in calls) == 6
    assert sum("ON CONFLICT (chunk_id)" in q for q, _, _ in calls) == 59
    assert sum("DELETE FROM chunks" in q for q, _, _ in calls) == 6
    assert "pg_advisory_xact_lock" in calls[0][0]


@pytest.mark.asyncio
async def test_failed_upsert_rolls_back_every_revision(monkeypatch):
    documents, chunks = load_corpus()
    connection = RecordingConnection()
    connection.fail_at = 8
    monkeypatch.setattr(db, "_pool", RecordingPool(connection))
    monkeypatch.setattr(db, "_embed_dim", 2)
    with pytest.raises(RuntimeError):
        await db.upsert_corpus(documents, [dict(c, embedding=[1, 0]) for c in chunks])
    assert connection.rolled_back and not connection.committed


@pytest.mark.asyncio
async def test_migration_refuses_to_silently_change_existing_vector_dimension(monkeypatch):
    pool = RecordingPool(RecordingConnection([{"type": "vector(1536)"}]))
    monkeypatch.setattr(db, "_pool", pool)
    monkeypatch.setattr(db, "_embed_dim", 768)
    with pytest.raises(ValueError, match="dimension"):
        await db.apply_migrations()
    assert not any("CREATE TABLE" in q for q, _, _ in pool.conn.calls)
