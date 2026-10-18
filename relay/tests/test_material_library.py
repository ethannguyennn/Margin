"""Upload storage and authenticated cloud retrieval; conversion is a separate stage."""
import hashlib
from unittest.mock import AsyncMock

import pytest

from _relay_helpers import PORTAL, v2_client, wait_material
from specs_relay import db
from specs_relay.schemas import MaterialLibrary


def upload(client, title="Synthetic tray check", revision="A", filename="tray.md"):
    source = b"1. Wipe the synthetic tray.\n2. Check the synthetic label.\n"
    response = client.post("/v1/materials", headers=PORTAL,
                           files={"file": (filename, source, "text/markdown")},
                           data={"doc_id": "SOP-991", "revision": revision, "title": title})
    assert response.status_code == 202, response.text
    material_id = response.json()["material_id"]
    assert response.headers["location"] == f"/v1/materials/{material_id}"
    return material_id, source


def test_upload_is_listed_searchable_and_original_is_byte_exact():
    client, _ = v2_client()
    with client:
        material_id, source = upload(client, filename='tray café.md')
        wait_material(client, material_id)
        response = client.get('/v1/materials?q=TRAY', headers=PORTAL)
        assert response.status_code == 200
        library = MaterialLibrary.model_validate(response.json())
        assert len(library.items) == 1 and library.next_offset is None
        item = library.items[0]
        assert (item.material_id, item.size_bytes, item.sha256) == (
            material_id, len(source), hashlib.sha256(source).hexdigest())
        assert not {'bytes', 'material_text'} & response.json()['items'][0].keys()
        assert client.get('/v1/materials?q=does-not-exist', headers=PORTAL).json()['items'] == []
        downloaded = client.get(f'/v1/materials/{material_id}/file', headers=PORTAL)
        assert downloaded.content == source
        assert downloaded.headers['content-type'].startswith('text/markdown')
        assert downloaded.headers['content-disposition'] == "attachment; filename*=UTF-8''tray%20caf%C3%A9.md"
        assert downloaded.headers['cache-control'] == response.headers['cache-control'] == 'no-store'
        assert downloaded.headers['x-content-type-options'] == 'nosniff'


def test_library_paginates_and_includes_failed_uploads():
    client, app = v2_client()
    with client:
        first, _ = upload(client, revision='A')
        second, source = upload(client, revision='B')
        wait_material(client, first)
        wait_material(client, second)
        # Conversion failure must not remove the source file from the library.
        app.state.pipeline.db.materials[first].update(status='failed', error='Conversion failed')
        page = client.get('/v1/materials?limit=1', headers=PORTAL).json()
        assert page['items'][0]['material_id'] == second and page['next_offset'] == 1
        page = client.get('/v1/materials?limit=1&offset=1', headers=PORTAL).json()
        assert page['items'][0]['material_id'] == first and page['items'][0]['status'] == 'failed'
        assert page['next_offset'] is None
        assert client.get(f'/v1/materials/{first}/file', headers=PORTAL).content == source


@pytest.mark.parametrize('path', ['/v1/materials', '/v1/materials/MAT-0001/file'])
def test_library_and_download_require_portal_auth(path):
    client, _ = v2_client()
    assert client.get(path).status_code == 401
    assert client.get(path, headers={'authorization': 'Bearer incorrect'}).status_code == 401


@pytest.mark.parametrize('query', ['limit=0', 'limit=101', 'offset=-1', 'q=' + 'x' * 121])
def test_library_rejects_unbounded_queries(query):
    client, _ = v2_client()
    assert client.get('/v1/materials?' + query, headers=PORTAL).status_code == 400


def test_missing_download_and_database_errors_are_not_successes(monkeypatch):
    client, app = v2_client()
    assert client.get('/v1/materials/not-found/file', headers=PORTAL).status_code == 404
    monkeypatch.setattr(app.state.pipeline.db, 'insert_material', AsyncMock(side_effect=RuntimeError('offline')))
    response = client.post('/v1/materials', headers=PORTAL, files={'file': ('x.txt', b'source')},
                           data={'doc_id': 'SOP-991', 'revision': 'A', 'title': 'Tray'})
    assert response.status_code == 503
    assert not app.state.pipeline.db.materials
    assert not app.state.jobs.tasks


def test_real_mode_cannot_acknowledge_a_memory_only_upload():
    client, app = v2_client()
    app.state.settings.mock_mode = False  # simulate an unavailable real DB module
    assert not app.state.pipeline.real_db
    response = client.post('/v1/materials', headers=PORTAL)
    assert response.status_code == 503
    assert not app.state.pipeline.db.materials
    assert client.get('/v1/materials', headers=PORTAL).status_code == 503


@pytest.mark.asyncio
async def test_library_sql_is_bounded_parameterized_and_metadata_only(monkeypatch):
    rows = AsyncMock(return_value=[])
    monkeypatch.setattr(db, '_rows', rows)
    await db.list_materials(query="x%' OR 1=1--", limit=26, offset=25)
    sql, params = rows.await_args.args
    assert "x%'" not in sql
    assert params == ("x%' OR 1=1--", 26, 25)
    assert 'material_text' not in sql and 'octet_length(bytes) AS size_bytes' in sql
    assert 'ORDER BY created_at DESC, material_id DESC LIMIT %s OFFSET %s' in sql

