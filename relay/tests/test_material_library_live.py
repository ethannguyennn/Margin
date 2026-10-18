"""Opt-in: real cloud Postgres + HTTP API, deterministic conversion only.

Never touches existing uploads or runs the app's global interrupted-job sweep.
Uses a random document ID, reconnects the DB and recreates the app, then cleans
up only the test's own rows. No provider call, token or source file is logged.
"""
import asyncio
import hashlib
import os
import secrets
import string
import sys

import httpx
import pytest

from specs_relay import db
from specs_relay.config import Settings
from specs_relay.main import build_pipeline, create_app


@pytest.mark.skipif(os.environ.get('SPECS_TEST_UPLOAD_DATABASE') != '1',
                    reason='opt-in cloud upload test; set SPECS_TEST_UPLOAD_DATABASE=1 and DATABASE_URL')
def test_upload_survives_relay_recreation_and_database_reconnection():
    asyncio.run(probe(), **({'loop_factory': asyncio.SelectorEventLoop} if sys.platform == 'win32' else {}))


async def probe():
    doc = 'T' + ''.join(secrets.choice(string.ascii_uppercase) for _ in range(4)) + '-991'
    token = secrets.token_urlsafe(32)
    settings = Settings()
    fixture_settings = Settings(_env_file=None, mock_mode=True, portal_token=token, sentry_dsn_relay='')
    source = b'1. Wipe the synthetic demonstration tray.\n2. Check the synthetic demonstration label.\n'
    material_id = None
    apps = []

    def app():
        pipe = build_pipeline(fixture_settings)
        pipe.db, pipe.real_db = db, True
        # Only conversion is synthetic; persistence/retrieval use the real cloud DB.
        current = create_app(fixture_settings.model_copy(update={'mock_mode': False}), pipeline=pipe)
        apps.append(current)
        return current

    try:
        await db.init_pool(settings)
        first = app()
        headers = {'Authorization': 'Bearer ' + token}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=first), base_url='http://test', headers=headers) as client:
            response = await client.post('/v1/materials', files={'file': ('synthetic-persistence.md', source)},
                                         data={'doc_id': doc, 'revision': 'A', 'title': 'Synthetic persistence probe'})
            assert response.status_code == 202, 'Upload must be committed before acknowledgement'
            material_id = response.json()['material_id']
            await asyncio.gather(*list(first.state.jobs.tasks.values()))
            row = await db.get_material(material_id, include_bytes=True)
            assert bytes(row['bytes']) == source and row['sha256'] == hashlib.sha256(source).hexdigest()
            assert row['status'] == 'ready'
        await first.state.jobs.shutdown()
        await db.close_pool()

        # New connections, new pipeline, no shared MockDB or client browser storage.
        await db.init_pool(settings)
        second = app()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=second), base_url='http://test', headers=headers) as client:
            response = await client.get('/v1/materials', params={'q': doc})
            assert response.status_code == 200
            assert [item['material_id'] for item in response.json()['items']] == [material_id]
            downloaded = await client.get(f'/v1/materials/{material_id}/file')
            assert downloaded.status_code == 200 and downloaded.content == source
            assert (await client.get(f'/v1/drafts/{doc}/A')).status_code == 200
            # A failed conversion also preserves the retrievable original.
            await db.set_material_status(material_id, 'failed', 'Synthetic test failure')
            assert (await client.get(f'/v1/materials/{material_id}/file')).content == source
            assert (await client.get(f'/v1/materials/{material_id}')).json()['status'] == 'failed'
    finally:
        for current in apps:
            await current.state.jobs.shutdown()
        if material_id is not None:
            await db.init_pool(settings)
            async with db.pool().connection() as conn:
                async with conn.transaction():
                    await conn.execute('DELETE FROM diagrams WHERE doc_id = %s AND revision = %s', (doc, 'A'))
                    await conn.execute('DELETE FROM drafts WHERE material_id = %s', (material_id,))
                    await conn.execute('DELETE FROM materials WHERE material_id = %s', (material_id,))
        await db.close_pool()
