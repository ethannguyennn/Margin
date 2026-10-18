from unittest.mock import AsyncMock

import pytest

from _relay_helpers import ask, v2_client
from specs_relay import db


def test_walkthrough_quotes_published_source_instead_of_paraphrased_body():
    client, app = v2_client()
    store = app.state.pipeline.db
    chunk = next(c for c in store.chunks if c.chunk_id == 'SOP-114:C:4.2')
    store.step_extras[chunk.chunk_id] = {
        'glance': 'Tighten M5 fasteners', 'body': 'Tighten the fasteners using the approved torque sequence.'}
    response = ask(client, 'walk me through the bracket assembly')
    assert response.status_code == 200
    result = response.json()
    assert result['verified'] is True
    step = next(s for s in result['walkthrough']['steps'] if s['step_id'] == chunk.chunk_id)
    citation = next(c for c in result['citations'] if c['chunk_id'] == chunk.chunk_id)
    assert citation['quote'] == chunk.text
    assert citation['quote'] != step['body']


def test_missing_source_support_refuses_the_whole_walkthrough(monkeypatch):
    client, app = v2_client()
    retriever = app.state.pipeline.retriever
    steps_for = retriever.steps_for

    async def missing_source(doc_id, revision):
        steps = await steps_for(doc_id, revision)
        return [step.model_copy(update={'source_text': None}) for step in steps]

    monkeypatch.setattr(retriever, 'steps_for', missing_source)
    response = ask(client, 'walk me through the bracket assembly')
    assert response.status_code == 200
    assert response.json()['outcome'] == 'not_found'
    assert not response.json().get('verified', False)


@pytest.mark.asyncio
async def test_database_citations_keep_source_text_and_pinned_revision(monkeypatch):
    query = AsyncMock(return_value=[{'chunk_id': 'SOP-150:A:1', 'doc_id': 'SOP-150', 'revision': 'A',
                                    'section': '1', 'text': 'Use the original source words.',
                                    'heading': 'Use the source', 'body': 'A paraphrase.'}])
    monkeypatch.setattr(db, '_step_rows', query)
    steps = await db.steps_for('SOP-150', 'A')
    query.assert_awaited_once_with('SOP-150', 'A')
    assert steps[0].source_text == 'Use the original source words.'
    assert steps[0].body == 'A paraphrase.'
