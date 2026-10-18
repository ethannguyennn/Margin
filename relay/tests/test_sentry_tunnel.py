import json
from unittest.mock import AsyncMock

import httpx
import pytest

from _relay_helpers import make_client
from specs_relay.routes import sentry_tunnel

DSN = 'https://public@o1.ingest.sentry.io/42'


def envelope(dsn=DSN):
    return json.dumps({'dsn': dsn}).encode() + b'\n{"type":"attachment","length":3}\n\xff\x00\x80'


def test_binary_envelope_is_forwarded_only_to_configured_dsn(monkeypatch):
    forward = AsyncMock(return_value=200)
    monkeypatch.setattr(sentry_tunnel, 'forward', forward)
    client, _ = make_client(sentry_dsn_app=DSN)
    body = envelope()
    response = client.post('/v1/sentry-tunnel', content=body)
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    forward.assert_awaited_once_with('https://o1.ingest.sentry.io/api/42/envelope/', body)


@pytest.mark.parametrize('dsn', ['http://127.0.0.1:8080/42',
                                  'https://public@o1.ingest.sentry.io/43',
                                  'https://other@o1.ingest.sentry.io/42'])
def test_tunnel_cannot_proxy_other_hosts_keys_or_projects(monkeypatch, dsn):
    forward = AsyncMock(return_value=200)
    monkeypatch.setattr(sentry_tunnel, 'forward', forward)
    client, _ = make_client(sentry_dsn_app=DSN)
    assert client.post('/v1/sentry-tunnel', content=envelope(dsn)).status_code == 400
    forward.assert_not_awaited()


@pytest.mark.parametrize('body', [b'', b'[]\n', b'not-json\n', b'\xff\n', b'{}\n'])
def test_malformed_envelopes_are_rejected(body):
    client, _ = make_client(sentry_dsn_app=DSN)
    assert client.post('/v1/sentry-tunnel', content=body).status_code == 400


def test_tunnel_caps_bytes_and_rejects_compression():
    client, _ = make_client(sentry_dsn_app=DSN)
    assert client.post('/v1/sentry-tunnel', content=b'x' * (sentry_tunnel.MAX_BYTES + 1)).status_code == 413
    assert client.post('/v1/sentry-tunnel', content=envelope(), headers={'content-encoding': 'gzip'}).status_code == 400


def test_unconfigured_tunnel_is_disabled():
    client, _ = make_client(sentry_dsn_app='')
    assert client.post('/v1/sentry-tunnel', content=envelope()).status_code == 404


@pytest.mark.parametrize('upstream', [302, 429, 500])
def test_upstream_failures_are_not_reported_as_delivery(monkeypatch, upstream):
    monkeypatch.setattr(sentry_tunnel, 'forward', AsyncMock(return_value=upstream))
    client, _ = make_client(sentry_dsn_app=DSN)
    assert client.post('/v1/sentry-tunnel', content=envelope()).status_code == 502


def test_network_errors_do_not_leak_envelopes(monkeypatch):
    monkeypatch.setattr(sentry_tunnel, 'forward', AsyncMock(side_effect=httpx.ConnectError('offline')))
    client, _ = make_client(sentry_dsn_app=DSN)
    assert client.post('/v1/sentry-tunnel', content=envelope()).status_code == 502


def test_tunnel_rate_limits_per_client(monkeypatch):
    monkeypatch.setattr(sentry_tunnel, 'forward', AsyncMock(return_value=200))
    client, _ = make_client(sentry_dsn_app=DSN)
    for _ in range(60):
        assert client.post('/v1/sentry-tunnel', content=envelope()).status_code == 200
    assert client.post('/v1/sentry-tunnel', content=envelope()).status_code == 429
