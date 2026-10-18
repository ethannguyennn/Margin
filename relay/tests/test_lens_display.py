from _relay_helpers import PORTAL, device, pair_and_claim, sid, v2_client
import base64


def feed(client, token):
    headers = device(token)
    stream = client.post('/v1/lens/display/stream', headers=headers).json()['stream_id']
    body = dict(stream_id=stream, sequence=1, connected=True, screen='STEP',
                frame=dict(header='1/3', main='Torque to 4 N-m', footer='next'))
    assert client.put('/v1/lens/display', headers=headers, json=body).status_code == 200
    return body


def test_acknowledged_frames_reach_portal_and_another_claimed_device():
    client, _ = v2_client()
    glasses = pair_and_claim(client)
    browser = pair_and_claim(client, 'Browser')
    body = feed(client, glasses['device_token'])
    for headers in (PORTAL, device(browser['device_token'])):
        rows = client.get('/v1/lens/displays', headers=headers)
        assert rows.status_code == 200
        assert 'frame' not in rows.json()[0]
        result = client.get('/v1/lens/displays/' + glasses['device_id'], headers=headers)
        assert result.headers['cache-control'] == 'no-store'
        assert result.json()['frame'] == {**body['frame'], 'graphic_id': None}
        assert result.json()['live'] is True
        assert 'stream_id' not in result.json()


def test_fail_closed_auth_and_workspace_isolation():
    client, _ = v2_client()
    glasses = pair_and_claim(client)
    feed(client, glasses['device_token'])
    unclaimed = client.post('/v1/devices/pair', json={'session_id': sid()}).json()
    other = client.post('/v1/orgs', json={'name': 'Other workspace'}).json()
    for headers in ({}, device('unknown'), device(unclaimed['device_token'])):
        assert client.get('/v1/lens/displays', headers=headers).status_code == 401
        assert client.post('/v1/lens/display/stream', headers=headers).status_code == 401
    assert client.get('/v1/lens/displays', headers=device(other['join_code'])).json() == []
    assert client.get('/v1/lens/displays/' + glasses['device_id'], headers=device(other['join_code'])).status_code == 404
    assert client.post('/v1/lens/display/stream', headers=PORTAL).status_code == 401


def test_stale_paused_restarted_and_out_of_order_updates():
    client, app = v2_client()
    clock = [1000.0]; app.state.display_feeds.clock = lambda: clock[0]
    glasses = pair_and_claim(client); headers = device(glasses['device_token'])
    body = feed(client, glasses['device_token']); url = '/v1/lens/displays/' + glasses['device_id']
    assert client.put('/v1/lens/display', headers=headers, json=body).status_code == 409
    clock[0] += 13
    assert client.get(url, headers=PORTAL).json()['live'] is False
    body.update(sequence=2, connected=False)
    assert client.put('/v1/lens/display', headers=headers, json=body).status_code == 200
    assert client.get(url, headers=PORTAL).json()['live'] is False
    client.post('/v1/lens/display/stream', headers=headers)
    assert client.put('/v1/lens/display', headers=headers, json={**body, 'sequence': 3}).status_code == 409
    app.state.display_feeds.rows.clear()
    assert client.put('/v1/lens/display', headers=headers, json=body).status_code == 410
    assert client.get(url, headers=PORTAL).json()['last_seen'] is None


def test_moving_device_does_not_leak_previous_workspace_frame():
    client, app = v2_client()
    glasses = pair_and_claim(client); body = feed(client, glasses['device_token'])
    other = client.post('/v1/orgs', json={'name': 'New workspace'}).json()
    app.state.pipeline.db.devices[glasses['device_id']]['org_id'] = other['org_id']
    assert client.get('/v1/lens/displays/' + glasses['device_id'], headers=PORTAL).status_code == 404
    view = client.get('/v1/lens/displays/' + glasses['device_id'], headers=device(other['join_code'])).json()
    assert view['live'] is False and 'frame' not in view
    assert client.put('/v1/lens/display', headers=device(glasses['device_token']), json={**body, 'sequence': 2}).status_code == 409


def test_frame_bounds_and_two_tiles():
    client, _ = v2_client(); glasses = pair_and_claim(client); headers = device(glasses['device_token'])
    body = feed(client, glasses['device_token']); body['sequence'] = 2
    assert client.put('/v1/lens/display', headers=headers, json={**body, 'frame': {**body['frame'], 'main': 'x' * 2001}}).status_code == 400
    assert client.put('/v1/lens/display', headers=headers, content=b'x' * 200001).status_code == 413
    tiles = [dict(slot=i, width=288, height=144, image=base64.b64encode(bytes(288 * 144 // 2)).decode()) for i in (0, 1)]
    body.update(screen='DIAGRAM', diagram=dict(diagram_id='DGM-test', tiles=tiles))
    assert client.put('/v1/lens/display', headers=headers, json=body).status_code == 200
    result = client.get('/v1/lens/displays/' + glasses['device_id'], headers=PORTAL).json()
    assert result['diagram']['tiles'] == tiles
    body['sequence'] = 3; body['diagram']['tiles'][1]['slot'] = 0
    assert client.put('/v1/lens/display', headers=headers, json=body).status_code == 400
