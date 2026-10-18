"""Publication unit tests use explicit snapshots, not a substitute production schema.

Live Tiger, Part 4 conversion and the HTTP flow remain separate integration gates.
"""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from part5_support import Cursor, RecordingConnection, RecordingPool
from margin_relay import db, walkthrough


def fixture_model(**values):
    def dump(**kwargs):
        def plain(value):
            if hasattr(value, 'model_dump'):
                return value.model_dump(**kwargs)
            if isinstance(value, list):
                return [plain(v) for v in value]
            return value
        return {k: plain(v) for k, v in vars(model).items() if k != 'model_dump'}
    model = SimpleNamespace(**values, model_dump=dump)
    return model


@pytest.fixture
def publication(monkeypatch):
    step = fixture_model(label='1', glance='Torque to 4 N-m', body='Torque the gland nut to 4 N-m.',
                         warning='Isolate power.', checkpoint='Check the witness mark.',
                         quotes=['Isolate power. Torque the gland nut to 4 N-m. Check the witness mark.'],
                         diagram=None, diagram_id=None, diagram_approved=False,
                         verify=fixture_model(ok=True, reason=None))
    draft = fixture_model(doc_id='SOP-150', revision='A', title='Seal swap', material_id='MAT-0001',
                          status='ready', steps=[step], warnings=['Isolate power.'])
    material = fixture_model(material_id='MAT-0001', pages=[fixture_model(page=1, text=step.quotes[0])], figures=[])
    monkeypatch.setattr(db, 'get_draft', AsyncMock(return_value=draft))
    monkeypatch.setattr(db, 'get_material_text', AsyncMock(return_value=material))
    monkeypatch.setattr(walkthrough, 'verify_for_publication', lambda s, m: SimpleNamespace(ok=True, reason=None))
    return draft, material


async def vectors(texts, settings, batch_size):
    assert batch_size == 32
    return [[1, 0, 0] for _ in texts]


@pytest.mark.asyncio
async def test_publish_preserves_quotes_separately_from_authored_body(monkeypatch, publication):
    draft, material = publication
    write = AsyncMock(return_value={'doc_id': 'SOP-150', 'revision': 'A', 'steps': 1})
    monkeypatch.setattr(db, 'publish_prepared', write)
    result = await walkthrough.publish_draft('SOP-150', 'A', settings=SimpleNamespace(embed_dim=3), embedder=vectors)
    assert result['steps'] == 1
    stored_draft, chunks, stored_material = write.await_args.args
    assert stored_draft is draft and stored_material is material
    assert chunks[0]['chunk_id'] == 'SOP-150:A:1'
    assert chunks[0]['text'] == '\n'.join(draft.steps[0].quotes)
    assert chunks[0]['body'] == draft.steps[0].body
    assert chunks[0]['warning'] == 'Isolate power.'
    assert chunks[0]['checkpoint'] == 'Check the witness mark.'
    assert chunks[1]['is_step'] is False and chunks[1]['text'] == 'Isolate power.'


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['verify', 'diagram', 'warning', 'empty', 'duplicate', 'changed_source', 'stale_diagram'])
async def test_publication_rejects_unreviewed_or_ungrounded_steps(monkeypatch, publication, failure):
    draft, material = publication
    if failure == 'verify':
        draft.steps[0].verify.ok = False
    elif failure == 'diagram':
        draft.steps[0].diagram = fixture_model(kind='schematic', alt='Seal')
        draft.steps[0].diagram_id = 'DGM-1'
    elif failure == 'warning':
        draft.warnings[:] = ['Invented warning not in the material']
    elif failure == 'empty':
        draft.steps[:] = []
    elif failure == 'duplicate':
        draft.steps.append(draft.steps[0])
    elif failure == 'stale_diagram':
        draft.steps[0].diagram_id = 'DGM-1'
    else:
        monkeypatch.setattr(walkthrough, 'verify_for_publication', lambda s, m: SimpleNamespace(ok=False, reason='Quote no longer in source'))
    write = AsyncMock()
    monkeypatch.setattr(db, 'publish_prepared', write)
    with pytest.raises(ValueError):
        await walkthrough.publish_draft(draft, settings=SimpleNamespace(embed_dim=3), embedder=vectors)
    write.assert_not_awaited()


@pytest.mark.asyncio
async def test_bad_embeddings_never_start_publication_transaction(monkeypatch, publication):
    async def broken(*args): return [[0, 0, 0]] * 2
    write = AsyncMock()
    monkeypatch.setattr(db, 'publish_prepared', write)
    with pytest.raises(ValueError):
        await walkthrough.publish_draft('SOP-150', 'A', settings=SimpleNamespace(embed_dim=3), embedder=broken)
    write.assert_not_awaited()


class PublishConnection(RecordingConnection):
    def __init__(self, draft, material, approved=False):
        super().__init__()
        self.snapshot = dict(draft.model_dump(), approved_at=datetime.now(timezone.utc) if approved else None)
        self.source = material.model_dump()

    async def execute(self, query, params=(), **kwargs):
        await super().execute(query, params, **kwargs)
        if 'SELECT * FROM drafts' in str(query):
            return Cursor([deepcopy(self.snapshot)])
        if 'SELECT material_text' in str(query):
            return Cursor([{'material_text': self.source, 'status': 'ready'}])
        if 'SELECT doc_id FROM documents' in str(query):
            return Cursor([{'doc_id': 'SOP-150'}])
        if 'SELECT diagram_id' in str(query):
            return Cursor([])
        return Cursor([])


def prepared(draft):
    s = draft.steps[0]
    return [dict(chunk_id='SOP-150:A:1', doc_id='SOP-150', revision='A', section='1',
                 is_step=True, step_order=1, heading=s.glance, text=s.quotes[0],
                 glance=s.glance, body=s.body, warning=s.warning, checkpoint=s.checkpoint,
                 diagram_id=s.diagram_id, embedding=[1, 0, 0])]


@pytest.mark.asyncio
async def test_publish_one_transaction_supersedes_prior_revision_without_repinning(monkeypatch, publication):
    draft, material = publication
    conn = PublishConnection(draft, material)
    pool = RecordingPool(conn)
    monkeypatch.setattr(db, '_pool', pool)
    monkeypatch.setattr(db, '_embed_dim', 3)
    result = await db.publish_prepared(draft, prepared(draft), material)
    assert result['steps'] == 1 and pool.checkouts == 1 and conn.committed
    queries = [q for q, _, _ in conn.calls]
    assert queries[0].startswith('SELECT pg_advisory_xact_lock')
    supersede = next(i for i, q in enumerate(queries) if "status = 'superseded'" in q)
    insert = next(i for i, q in enumerate(queries) if 'INSERT INTO documents' in q)
    assert supersede < insert
    assert any('UPDATE drafts SET approved_at' in q for q in queries)
    assert any("status = 'approved'" in q for q in queries)
    assert not any('UPDATE assignments' in q for q in queries)


@pytest.mark.asyncio
async def test_publish_query_failure_rolls_back_all_changes(monkeypatch, publication):
    draft, material = publication
    conn = PublishConnection(draft, material)
    conn.fail_at = 8
    monkeypatch.setattr(db, '_pool', RecordingPool(conn))
    monkeypatch.setattr(db, '_embed_dim', 3)
    with pytest.raises(RuntimeError):
        await db.publish_prepared(draft, prepared(draft), material)
    assert conn.rolled_back and not conn.committed


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['draft', 'material'])
async def test_concurrent_edit_rejected_before_document_mutation(monkeypatch, publication, change):
    draft, material = publication
    conn = PublishConnection(draft, material)
    if change == 'draft': conn.snapshot['title'] = 'A newer edit'
    else: conn.source = {'pages': []}
    monkeypatch.setattr(db, '_pool', RecordingPool(conn))
    monkeypatch.setattr(db, '_embed_dim', 3)
    with pytest.raises(ValueError, match='changed'):
        await db.publish_prepared(draft, prepared(draft), material)
    assert not any('UPDATE documents' in q for q, _, _ in conn.calls)


@pytest.mark.asyncio
async def test_repeated_approval_does_not_reactivate_a_superseded_revision(monkeypatch, publication):
    draft, material = publication
    conn = PublishConnection(draft, material, approved=True)
    monkeypatch.setattr(db, '_pool', RecordingPool(conn))
    monkeypatch.setattr(db, '_embed_dim', 3)
    await db.publish_prepared(draft, prepared(draft), material)
    assert not any('UPDATE documents' in q for q, _, _ in conn.calls)


@pytest.mark.asyncio
async def test_database_rechecks_diagram_approval_under_publication_lock(monkeypatch, publication):
    draft, material = publication
    draft.steps[0].diagram = fixture_model(kind='schematic', alt='Seal')
    draft.steps[0].diagram_id = 'DGM-0001'
    draft.steps[0].diagram_approved = True
    conn = PublishConnection(draft, material)
    monkeypatch.setattr(db, '_pool', RecordingPool(conn))
    monkeypatch.setattr(db, '_embed_dim', 3)
    with pytest.raises(ValueError, match='diagram is not approved'):
        await db.publish_prepared(draft, prepared(draft), material)
    assert conn.rolled_back and not any('UPDATE documents' in q for q, _, _ in conn.calls)


@pytest.mark.asyncio
async def test_publishing_cannot_overwrite_an_existing_v1_revision(monkeypatch, publication):
    draft, material = publication
    conn = PublishConnection(draft, material)
    original = conn.execute
    async def execute(query, params=(), **kwargs):
        cursor = await original(query, params, **kwargs)
        if 'SELECT status FROM documents' in str(query):
            return Cursor([{'status': 'effective'}])
        return cursor
    conn.execute = execute
    monkeypatch.setattr(db, '_pool', RecordingPool(conn))
    monkeypatch.setattr(db, '_embed_dim', 3)
    with pytest.raises(ValueError, match='already published'):
        await db.publish_prepared(draft, prepared(draft), material)
    assert conn.rolled_back and not any('UPDATE documents' in q for q, _, _ in conn.calls)


@pytest.mark.asyncio
async def test_published_quote_chunks_feed_actual_v1_ask_with_verbatim_citations(monkeypatch, publication):
    """Actual HTTP handler and verifier; publication/provider/database are fixtures."""
    import httpx
    from uuid import uuid4
    from margin_relay.config import Settings
    from margin_relay.main import build_pipeline, create_app
    from margin_relay.pipeline.sanitize import sanitize
    from margin_relay.pipeline.verify import verify
    from margin_relay.schemas import Chunk, Draft, DraftCitation, RetrievalResult

    captured = []
    async def commit(draft, chunks, material):
        captured.extend(chunks)
        return {'doc_id': draft.doc_id, 'revision': draft.revision, 'steps': len(draft.steps)}
    monkeypatch.setattr(db, 'publish_prepared', commit)
    await walkthrough.publish_draft('SOP-150', 'A', settings=SimpleNamespace(embed_dim=3), embedder=vectors)
    chunk = Chunk(**captured[0], title='Seal swap')
    settings = Settings(mock_mode=True, _env_file=None)
    pipeline = build_pipeline(settings)
    pipeline.retriever = SimpleNamespace(retrieve=AsyncMock(return_value=RetrievalResult(chunks=[chunk], best_sim=1, best_rrf=1)))
    pipeline.generator = SimpleNamespace(generate=AsyncMock(return_value=Draft(
        answerable=True, glance='Torque to 4 N-m', body='Torque the gland nut to 4 N-m.',
        citations=[DraftCitation(chunk_id=chunk.chunk_id, quote=chunk.text)])))
    pipeline.verify, pipeline.sanitize = verify, sanitize
    app = create_app(settings, pipeline)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://fixture') as client:
        response = await client.post('/v1/ask', json={'session_id': str(uuid4()), 'text': 'How tight is the gland nut?'})
    payload = response.json()
    assert response.status_code == 200 and payload['outcome'] == 'answered' and payload['verified']
    assert payload['citations'][0]['chunk_id'] == 'SOP-150:A:1'
    assert payload['citations'][0]['quote'] == publication[0].steps[0].quotes[0]


@pytest.mark.asyncio
async def test_published_walkthrough_preserves_v2_extras_when_shared_contract_is_merged(monkeypatch):
    from margin_relay.schemas import Step
    if 'warning' not in Step.model_fields:
        pytest.skip('V2 Step schema is deferred until the Part 3 merge')
    row = {'chunk_id': 'SOP-150:A:1', 'doc_id': 'SOP-150', 'revision': 'A', 'section': '1',
           'heading': 'Torque', 'text': 'The full verbatim source. ' * 50, 'glance': 'Torque to 4 N-m',
           'body': 'Torque the gland nut to 4 N-m.', 'warning': 'Isolate power.',
           'checkpoint': 'Check the witness mark.', 'diagram': {'diagram_id': 'DGM-1', 'width': 576, 'height': 144, 'alt': 'Seal'}}
    monkeypatch.setattr(db, 'document_for', AsyncMock(return_value={'revision': 'A', 'title': 'Seal swap'}))
    monkeypatch.setattr(db, '_step_rows', AsyncMock(return_value=[row]))
    result = await walkthrough.build_walkthrough('SOP-150')
    step = result['steps'][0]
    assert step['body'] == row['body'] and step['warning'] == row['warning']
    assert step['checkpoint'] == row['checkpoint'] and step['diagram'] == row['diagram']


@pytest.mark.asyncio
async def test_shared_contract_allows_descriptive_step_labels(monkeypatch, publication):
    publication[0].steps[0].label = 'isolate'
    write = AsyncMock(return_value={})
    monkeypatch.setattr(db, 'publish_prepared', write)
    await walkthrough.publish_draft('SOP-150', 'A', settings=SimpleNamespace(embed_dim=3), embedder=vectors)
    assert write.await_args.args[1][0]['chunk_id'] == 'SOP-150:A:isolate'
