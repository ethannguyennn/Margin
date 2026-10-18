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
    monkeypatch.setattr(app.state.pipeline.db, 'walkthrough_citations', AsyncMock(return_value=[]))
    response = ask(client, 'walk me through the bracket assembly')
    assert response.status_code == 500
    assert response.json()['outcome'] == 'error'
    assert not response.json().get('verified', False)


@pytest.mark.asyncio
async def test_database_citations_keep_source_text_and_pinned_revision(monkeypatch):
    query = AsyncMock(return_value=[{'chunk_id': 'SOP-150:A:1', 'doc_id': 'SOP-150', 'revision': 'A',
                                    'section': '1', 'text': 'Use the original source words.',
                                    'body': 'A paraphrase.'}])
    monkeypatch.setattr(db, '_step_rows', query)
    citations = await db.walkthrough_citations('SOP-150', 'A')
    query.assert_awaited_once_with('SOP-150', 'A')
    assert citations[0].quote == 'Use the original source words.'
