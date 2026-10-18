"""CORS: the WebView is a real browser with real preflights."""

from __future__ import annotations

import logging

import pytest

from _relay_helpers import DEVICE_ORIGIN, ORIGIN, make_client, sid

ROUTES = [("POST", "/v1/ask"), ("GET", "/v1/health"), ("POST", "/v1/deviation"),
          ("GET", "/v1/procedures"), ("GET", "/v1/procedures/SOP-114/steps"),
          ("POST", "/v1/ingest"),
          # v2 lens routes (the WebView calls these cross-origin) and portal routes
          ("POST", "/v1/devices/pair"), ("GET", "/v1/devices/me"), ("GET", "/v1/assignments/next"),
          ("POST", "/v1/progress"), ("GET", "/v1/diagrams/DGM-0001"),
          ("PUT", "/v1/drafts/SOP-150/A/steps/1"), ("POST", "/v1/materials")]
REQUIRED_HEADERS = ["content-type", "sentry-trace", "baggage", "x-session-id"]


@pytest.fixture
def client():
    return make_client()[0]


def preflight(client, path, origin, method="POST", headers=REQUIRED_HEADERS):
    return client.options(path, headers={"Origin": origin,
                                         "Access-Control-Request-Method": method,
                                         "Access-Control-Request-Headers": ",".join(headers)})


@pytest.mark.parametrize("origin", [ORIGIN, DEVICE_ORIGIN])
@pytest.mark.parametrize("method,path", ROUTES)
def test_preflight_2xx_on_every_route(client, origin, method, path):
    r = preflight(client, path, origin, method)
    assert 200 <= r.status_code < 300
    assert r.headers["access-control-allow-origin"] == origin
    allowed = {h.strip().lower() for h in r.headers["access-control-allow-headers"].split(",")}
    assert set(REQUIRED_HEADERS) <= allowed
    assert method in r.headers["access-control-allow-methods"]


@pytest.mark.parametrize("method,path", ROUTES)
def test_bare_options_2xx_on_every_route(client, method, path):
    r = client.options(path)
    assert 200 <= r.status_code < 300


def test_rejected_origin_is_logged_at_warn(client, caplog):
    caplog.set_level(logging.WARNING, logger="margin.relay")
    r = preflight(client, "/v1/ask", "https://evil.example")
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers
    assert any("CORS rejected origin 'https://evil.example'" in m for m in caplog.messages)


def test_simple_request_from_wrong_origin_gets_no_acao(client, caplog):
    caplog.set_level(logging.WARNING, logger="margin.relay")
    r = client.get("/v1/health", headers={"Origin": "http://localhost:9999"})
    assert "access-control-allow-origin" not in r.headers
    assert any("localhost:9999" in m for m in caplog.messages)


def test_actual_request_carries_cors_and_trace_headers(client):
    r = client.post("/v1/ask", json={"session_id": sid(), "text": "how tight is the m5"},
                    headers={"Origin": ORIGIN, "x-session-id": "abc"})
    assert r.headers["access-control-allow-origin"] == ORIGIN
    assert "x-trace-id" in r.headers["access-control-expose-headers"].lower()


def test_error_responses_carry_cors_headers():
    client, app = make_client()

    def boom(_t):
        raise RuntimeError("bug")

    app.state.pipeline.classify = boom
    r = client.post("/v1/ask", json={"session_id": sid(), "text": "x"}, headers={"Origin": ORIGIN})
    assert r.status_code == 500
    assert r.headers["access-control-allow-origin"] == ORIGIN  # browser can read the error
    r = client.post("/v1/ask", json={"text": "x"}, headers={"Origin": ORIGIN})
    assert r.status_code == 400 and r.headers["access-control-allow-origin"] == ORIGIN


def test_origin_regex_for_lan_dev():
    client, _ = make_client(allowed_origins="", allowed_origin_regex=r"^http://192\.168\.\d+\.\d+:5174$")
    assert preflight(client, "/v1/ask", "http://192.168.1.23:5174").status_code == 200
    assert preflight(client, "/v1/ask", "http://10.0.0.2:5174").status_code == 400


LAN_REGEX = r"^http://(192\.168|10)\.\d+\.\d+(\.\d+)?:517[45]$"  # as in .env.example


@pytest.mark.parametrize("origin,ok", [
    ("http://192.168.1.23:5174", True),   # lens app from a phone on the LAN
    ("http://192.168.1.23:5175", True),   # iPhone companion on the LAN
    ("http://10.0.0.7:5175", True),
    ("http://192.168.1.23:5176", False),
    ("https://192.168.1.23:5175", False),
    ("http://evil.example:5175", False),
])
def test_documented_lan_regex(origin, ok):
    client, _ = make_client(allowed_origins="", allowed_origin_regex=LAN_REGEX)
    assert (preflight(client, "/v1/ask", origin).status_code == 200) is ok


def test_companion_origin_preflights_its_routes():
    client, _ = make_client(allowed_origins="http://localhost:5174,http://localhost:5175")
    for method, path in [("GET", "/v1/health"), ("GET", "/v1/procedures"),
                         ("GET", "/v1/procedures/SOP-114/steps"), ("POST", "/v1/ask"),
                         ("POST", "/v1/deviation")]:
        r = preflight(client, path, "http://localhost:5175", method)
        assert r.status_code == 200 and r.headers["access-control-allow-origin"] == \
            "http://localhost:5175"


def test_trailing_slash_in_config_is_tolerated():
    client, _ = make_client(allowed_origins=f" {ORIGIN}/ , ")
    assert preflight(client, "/v1/ask", ORIGIN).status_code == 200
