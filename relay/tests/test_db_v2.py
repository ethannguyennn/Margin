from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from part5_support import RecordingConnection, RecordingPool, Cursor
from specs_relay import db

# The industrial HX-2 bank these tests were written against (the demo bank in corpus/ is coffee).
HX2_CORPUS = Path(__file__).parent / "fixtures" / "hx2-corpus"
HX2_QA = HX2_CORPUS.parent / "hx2-qa.jsonl"


@pytest.mark.asyncio
async def test_migration_runs_both_scripts_in_one_transaction(monkeypatch):
    conn = RecordingConnection()
    monkeypatch.setattr(db, '_pool', RecordingPool(conn))
    monkeypatch.setattr(db, '_embed_dim', 3)
    await db.apply_migrations()
    await db.apply_migrations()
    scripts = [q for q, _, _ in conn.calls if 'CREATE TABLE IF NOT EXISTS materials' in q]
    assert len(scripts) == 2
    assert "create_hypertable('progress', 'ts', if_not_exists => TRUE)" in scripts[0]
    assert "coalesce(step_id, ''), kind, ts" in scripts[0]
    assert 'octet_length(bytes) <= 20 * 1024 * 1024' in scripts[0]
    assert 'object storage' in scripts[0]
    assert not any('DROP ' in q for q, _, _ in conn.calls)
    assert conn.committed


@pytest.mark.asyncio
async def test_lexical_leg_ors_stemmed_terms_and_keeps_revision_filter(monkeypatch):
    rows = AsyncMock(return_value=[])
    monkeypatch.setattr(db, '_rows', rows)
    await db._fts_rows('how tight is the M5 bracket?', revision=None)
    query, params = rows.await_args.args
    assert "replace(websearch_to_tsquery('english', %s)::text, ' & ', ' | ')::tsquery" in query
    assert "d.status = 'effective'" in query
    assert params == ('how tight is the M5 bracket?', 20)


@pytest.mark.asyncio
async def test_material_size_boundary_and_default_read_never_selects_bytes(monkeypatch):
    rows = AsyncMock(return_value=[{'value': 1}])
    monkeypatch.setattr(db, '_rows', rows)
    assert await db.insert_material('synthetic.txt', 'text/plain', b'x', 'SOP-150', 'A', 'Pump seal') == 'MAT-0001'
    insert, params = rows.await_args.args
    assert 'INSERT INTO materials' in insert and len(params[4]) == 64
    with pytest.raises(ValueError, match='20 MB'):
        await db.insert_material('x', 'text/plain', b'x' * (db.MAX_FILE_BYTES + 1), 'SOP-150', 'A', 'Pump')
    with pytest.raises(ValueError):
        await db.insert_material('x', 'text/plain', b'x', 'bad', 'A', 'Pump')
    await db.get_material('MAT-0001')
    assert ', bytes' not in rows.await_args.args[0]
    await db.get_material('MAT-0001', include_bytes=True)
    assert ', bytes' in rows.await_args.args[0]


@pytest.mark.asyncio
async def test_device_token_never_selected_in_list_or_claim(monkeypatch):
    rows = AsyncMock(return_value=[])
    monkeypatch.setattr(db, '_rows', rows)
    await db.list_devices()
    assert 'token_sha256' not in rows.await_args.args[0]
    assert await db.claim_device('4f7k', 'Bay 3') is None
    query, params = rows.await_args.args
    assert 'claimed_at IS NULL AND pair_expires > now()' in query
    assert params == ('Bay 3', None, '4F7K')  # unscoped: the org stays as it was
    assert 'token_sha256' not in query


@pytest.mark.asyncio
async def test_create_device_expires_open_codes_and_rejects_plain_tokens(monkeypatch):
    conn = RecordingConnection()
    monkeypatch.setattr(db, '_pool', RecordingPool(conn))
    monkeypatch.setattr(db, '_next_id', AsyncMock(return_value='LNS-0001'))
    expires = datetime.now(timezone.utc) + timedelta(minutes=15)
    assert await db.create_device('a' * 64, '4F7K', expires) == 'LNS-0001'
    assert 'pair_code = NULL' in conn.calls[0][0]
    with pytest.raises(ValueError, match='SHA-256'):
        await db.create_device('secret-plaintext', '4F7K', expires)


@pytest.mark.asyncio
async def test_assignment_resolves_and_pins_revision_in_insert(monkeypatch):
    rows = AsyncMock(return_value=[{'assignment_id': 'ASN-0001'}])
    monkeypatch.setattr(db, '_rows', rows)
    monkeypatch.setattr(db, '_next_id', AsyncMock(return_value='ASN-0001'))
    await db.create_assignment('LNS-0001', 'SOP-150')
    query, params = rows.await_args.args
    assert 'INSERT INTO assignments' in query and "d.status = 'effective'" in query
    assert 'dev.claimed_at IS NOT NULL' in query
    await db.create_assignment('LNS-0001', 'SOP-150', 'A')
    assert 'd.revision = %s' in rows.await_args.args[0]
    assert rows.await_args.args[1][-1] == 'A'
    await db.next_assignment('LNS-0001')
    assert 'FOR UPDATE SKIP LOCKED' in rows.await_args.args[0]
    assert 'delivered_at = now()' in rows.await_args.args[0]


@pytest.mark.asyncio
async def test_progress_dedup_counts_only_insertions_and_preserves_device_scope(monkeypatch):
    conn = RecordingConnection([{'assignment_id': 'ASN-0001'}])
    execute = conn.execute
    seen = set()

    async def dedupe(query, params=(), **kwargs):
        await execute(query, params, **kwargs)
        if 'INSERT INTO progress' in str(query):
            if params[:4] in seen:
                return Cursor([])
            seen.add(params[:4])
            return Cursor([{'assignment_id': 'ASN-0001'}])
        return Cursor([])

    conn.execute = dedupe
    monkeypatch.setattr(db, '_pool', RecordingPool(conn))
    event = {'assignment_id': 'ASN-0001', 'step_id': None, 'kind': 'task_started', 'ts': 1792280000000}
    assert await db.insert_progress([event, event], device_id='LNS-0001') == 1
    assert await db.insert_progress([event], device_id='LNS-0001') == 0
    query, params, _ = conn.calls[0]
    assert 'ON CONFLICT DO NOTHING' in query
    assert params[4] == 'LNS-0001' and 'a.device_id = %s' in query
    assert params[0].tzinfo is not None


@pytest.mark.asyncio
async def test_progress_failure_rolls_back_and_never_exposes_error(monkeypatch, caplog):
    conn = RecordingConnection()
    conn.fail_at = 2
    monkeypatch.setattr(db, '_pool', RecordingPool(conn))
    events = [{'assignment_id': 'ASN-1', 'step_id': None, 'kind': 'task_started', 'ts': 1000}] * 2
    assert await db.insert_progress(events, device_id='LNS-1') == 0
    assert conn.rolled_back and not conn.committed
    assert 'Progress write skipped (RuntimeError)' in caplog.text
    assert await db.insert_progress([dict(events[0], ts=float('nan'))], device_id='LNS-1') == 0


@pytest.mark.asyncio
async def test_board_reads_latest_step_and_inline_deviations(monkeypatch):
    rows = AsyncMock(return_value=[])
    monkeypatch.setattr(db, '_rows', rows)
    await db.progress_board(1792280000000)
    query, params = rows.await_args.args
    assert 'jsonb_agg' in query and 'FROM deviations' in query
    assert 'step_started_at' in query and "kind = 'step_started'" in query
    assert 'last_step.step_id' in query and 'step_id IS NOT NULL' in query
    assert params[0] == params[1] and params[0].tzinfo is not None


@pytest.mark.asyncio
async def test_edit_rejects_published_revision_before_mutating(monkeypatch):
    conn = RecordingConnection([{'approved_at': datetime.now(timezone.utc)}])
    monkeypatch.setattr(db, '_pool', RecordingPool(conn))
    step = SimpleNamespace(label='1')
    with pytest.raises(ValueError, match='immutable'):
        await db.update_draft_step('SOP-150', 'A', '1', step)
    assert conn.rolled_back and not any('UPDATE drafts SET' in q for q, _, _ in conn.calls)


def test_shared_v2_contract_available_after_scaffold_merge():
    from specs_relay import schemas
    if not hasattr(schemas, 'ProcedureDraft'):
        pytest.skip('Part 3 v2-scaffold-relay is pending the team merge')
    for name in ('ProcedureDraft', 'DraftStep', 'MaterialText', 'DiagramSpec', 'ProgressEvent'):
        assert hasattr(schemas, name)


@pytest.mark.asyncio
async def test_seed_from_drafts_republishes_only_approved_snapshots(monkeypatch, capsys):
    from db import seed
    from specs_relay import walkthrough
    approved = SimpleNamespace(doc_id='SOP-150', revision='A')
    monkeypatch.setattr(db, 'get_settings', lambda: SimpleNamespace())
    monkeypatch.setattr(db, 'init_pool', AsyncMock())
    monkeypatch.setattr(db, 'close_pool', AsyncMock())
    monkeypatch.setattr(db, 'validate_capabilities', AsyncMock(return_value={'fixture': True}))
    monkeypatch.setattr(db, 'apply_migrations', AsyncMock())
    monkeypatch.setattr(db, 'approved_drafts', AsyncMock(return_value=[approved]))
    publish = AsyncMock(return_value={'doc_id': 'SOP-150', 'revision': 'A', 'steps': 1})
    monkeypatch.setattr(walkthrough, 'publish_draft', publish)
    assert await seed.main(['--from-drafts']) == 0
    assert publish.await_args.args == (approved,)
    assert 'SOP-150' in capsys.readouterr().out


@pytest.mark.asyncio
async def test_migrate_only_never_embeds_or_seeds(monkeypatch):
    from db import seed
    monkeypatch.setattr(db, 'get_settings', lambda: SimpleNamespace())
    monkeypatch.setattr(db, 'init_pool', AsyncMock())
    monkeypatch.setattr(db, 'close_pool', AsyncMock())
    monkeypatch.setattr(db, 'validate_capabilities', AsyncMock(return_value={}))
    monkeypatch.setattr(db, 'storage_counts', AsyncMock(return_value={'documents': 6, 'chunks': 59}))
    migrate = AsyncMock()
    monkeypatch.setattr(db, 'apply_migrations', migrate)
    ingest = AsyncMock()
    monkeypatch.setattr(seed, 'ingest', ingest)
    assert await seed.main(['--migrate-only']) == 0
    migrate.assert_awaited_once()
    ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_v1_reseed_cannot_replace_portal_published_revision(monkeypatch):
    from db.seed import load_corpus
    documents, chunks = load_corpus(HX2_CORPUS)
    documents = [d for d in documents if d['doc_id'] == 'SOP-114']
    chunks = [dict(c, embedding=[1, 0]) for c in chunks if c['doc_id'] == 'SOP-114']
    conn = RecordingConnection()
    original = conn.execute
    async def execute(query, params=(), **kwargs):
        cursor = await original(query, params, **kwargs)
        if 'SELECT revision FROM drafts' in str(query):
            return Cursor([{'revision': 'D'}])
        return cursor
    conn.execute = execute
    monkeypatch.setattr(db, '_pool', RecordingPool(conn))
    monkeypatch.setattr(db, '_embed_dim', 2)
    await db.upsert_corpus(documents, chunks)
    document_writes = [params for q, params, _ in conn.calls if 'INSERT INTO documents' in q]
    assert len(document_writes) == 1
    assert document_writes[0][1] == 'C' and document_writes[0][3] == 'superseded'
    assert all(params[2] != 'D' for q, params, _ in conn.calls if 'INSERT INTO chunks' in q)


@pytest.mark.asyncio
async def test_storage_evidence_reports_absent_tables_without_reading_uploads(monkeypatch):
    async def rows(query, params=()):
        if isinstance(query, str) and 'to_regclass' in query:
            return [{'present': params[0] in {'documents', 'chunks'}}]
        return [{'n': 59}]
    monkeypatch.setattr(db, '_rows', rows)
    counts = await db.storage_counts()
    assert counts['documents'] == 59 and counts['chunks'] == 59
    assert counts['materials'] is None and counts['progress'] is None


@pytest.mark.asyncio
async def test_progress_without_authenticated_device_fails_closed(monkeypatch):
    pool = RecordingPool()
    monkeypatch.setattr(db, '_pool', pool)
    assert await db.insert_progress([{'assignment_id': 'ASN-1', 'step_id': None, 'kind': 'task_started', 'ts': 1000}]) == 0
    assert pool.checkouts == 0
