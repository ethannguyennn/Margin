"""Portal + device auth (README-PART-3 section 5), all on the mock relay."""

from __future__ import annotations

import hashlib
import logging

import pytest

from _relay_helpers import PORTAL, PORTAL_TOKEN, device, pair_and_claim, sid, v2_client
from margin_relay.auth import RateLimiter, RateLimited, new_pair_code
from margin_relay.schemas import PAIR_CODE_ALPHABET

PORTAL_ROUTES = [
    ("get", "/v1/devices"), ("post", "/v1/devices/claim"), ("post", "/v1/assignments"),
    ("get", "/v1/progress"), ("post", "/v1/materials"), ("get", "/v1/materials/MAT-0001"),
    ("get", "/v1/materials/MAT-0001/text"), ("get", "/v1/drafts/SOP-150/A"),
    ("put", "/v1/drafts/SOP-150/A/steps/1"), ("post", "/v1/drafts/SOP-150/A/approve"),
    ("post", "/v1/drafts/SOP-150/A/diagrams/DGM-0001/approve"),
    ("get", "/v1/diagrams/DGM-0001/preview.png"),
]
LENS_ROUTES = [("get", "/v1/devices/me"), ("get", "/v1/assignments/next"),
               ("post", "/v1/progress"), ("get", "/v1/diagrams/DGM-0001")]


@pytest.mark.parametrize("method,path", PORTAL_ROUTES)
@pytest.mark.parametrize("headers", [{}, {"authorization": "Bearer wrong"}, {"authorization": PORTAL_TOKEN}])
def test_portal_routes_401_without_the_token(method, path, headers):
    client, _ = v2_client()
    kw = {"json": {}} if method in ("post", "put") and "materials" not in path else {}
    r = getattr(client, method)(path, headers=headers, **kw)
    assert r.status_code == 401, (path, r.status_code, r.text)
    b = r.json()
    assert b["outcome"] == "error" and b["error"]["code"] == "unauthorized" and b["trace_id"]


def test_portal_disabled_when_token_unset():
    client, _ = v2_client(portal_token=None)
    r = client.get("/v1/devices", headers=PORTAL)
    assert r.status_code == 401 and "PORTAL_TOKEN is not configured" in r.json()["error"]["message"]


def test_portal_token_grants_access():
    client, _ = v2_client()
    assert client.get("/v1/devices", headers=PORTAL).status_code == 200


@pytest.mark.parametrize("method,path", LENS_ROUTES)
@pytest.mark.parametrize("headers", [{}, {"authorization": "Bearer not-a-device"}, PORTAL])
def test_lens_routes_401_without_a_device_token(method, path, headers):
    client, _ = v2_client()
    kw = {"json": {"events": []}} if method == "post" else {}
    r = getattr(client, method)(path, headers=headers, **kw)
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


def test_pair_mints_a_token_and_stores_only_its_hash():
    client, app = v2_client()
    p = client.post("/v1/devices/pair", json={"session_id": sid()}).json()
    assert p["claimed"] is False and p["worker_name"] is None
    assert len(p["pair_code"]) == 4 and set(p["pair_code"]) <= set(PAIR_CODE_ALPHABET)
    assert len(p["device_token"]) >= 40
    stored = app.state.pipeline.db.devices[p["device_id"]]
    assert stored["token_sha256"] == hashlib.sha256(p["device_token"].encode()).hexdigest()
    assert p["device_token"] not in repr(stored)


def test_me_polls_until_claimed_and_never_leaks_the_token_to_the_portal():
    client, _ = v2_client()
    p = client.post("/v1/devices/pair", json={"session_id": sid()}).json()
    me = client.get("/v1/devices/me", headers=device(p["device_token"])).json()
    assert me["claimed"] is False and me["pair_code"] == p["pair_code"]
    claimed = client.post("/v1/devices/claim", headers=PORTAL,
                          json={"pair_code": p["pair_code"].lower(), "worker_name": "Bay 3"}).json()
    assert claimed["claimed"] is True and claimed["device_token"] == ""
    me = client.get("/v1/devices/me", headers=device(p["device_token"])).json()
    assert me == {**me, "claimed": True, "worker_name": "Bay 3", "device_token": p["device_token"]}
    listed = client.get("/v1/devices", headers=PORTAL).json()
    assert listed[0]["device_id"] == p["device_id"] and "device_token" not in listed[0]
    assert listed[0]["pair_code"] is None  # no open code once claimed


def test_claim_unknown_or_reused_code_is_404():
    client, _ = v2_client()
    p = pair_and_claim(client)
    r = client.post("/v1/devices/claim", headers=PORTAL, json={"pair_code": p["pair_code"], "worker_name": "x"})
    assert r.status_code == 404
    r = client.post("/v1/devices/claim", headers=PORTAL, json={"pair_code": "0O1I", "worker_name": "x"})
    assert r.status_code == 400  # ambiguous characters are not in the alphabet


def test_expired_unclaimed_code_forces_a_repair():
    client, app = v2_client(pair_code_ttl_s=60)
    p = client.post("/v1/devices/pair", json={"session_id": sid()}).json()
    row = app.state.pipeline.db.devices[p["device_id"]]
    row["pair_expires"] = row["created_at"]  # already expired
    assert client.get("/v1/devices/me", headers=device(p["device_token"])).status_code == 401
    r = client.post("/v1/devices/claim", headers=PORTAL, json={"pair_code": p["pair_code"], "worker_name": "x"})
    assert r.status_code == 404


def test_pair_is_rate_limited_per_ip():
    client, _ = v2_client(pair_rate_per_min=3)
    codes = [client.post("/v1/devices/pair", json={"session_id": sid()}).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_rate_limiter_window_slides():
    now = [0.0]
    limiter = RateLimiter(2, clock=lambda: now[0])
    limiter.check("ip"); limiter.check("ip")  # noqa: E702
    with pytest.raises(RateLimited):
        limiter.check("ip")
    now[0] = 60.0
    limiter.check("ip")  # the window moved on
    limiter.check("other")  # keys are independent


def test_pair_codes_avoid_lookalikes():
    assert not set("0O1I") & set(PAIR_CODE_ALPHABET)
    assert all(set(new_pair_code()) <= set(PAIR_CODE_ALPHABET) for _ in range(200))


def test_a_device_cannot_read_another_devices_assignment_or_progress():
    client, app = v2_client()
    a, b = pair_and_claim(client, "Bay 3"), pair_and_claim(client, "Bay 4")
    r = client.post("/v1/assignments", headers=PORTAL, json={"device_id": a["device_id"], "doc_id": "SOP-114"})
    assignment_id = r.json()["assignment_id"]
    assert client.get("/v1/assignments/next", headers=device(b["device_token"])).status_code == 204
    event = {"assignment_id": assignment_id, "step_id": "SOP-114:C:4.1", "kind": "step_started", "ts": 1.0}
    assert client.post("/v1/progress", headers=device(b["device_token"]),
                       json={"events": [event]}).json() == {"accepted": 0}
    assert app.state.pipeline.db.progress == {}
    assert client.get("/v1/assignments/next", headers=device(a["device_token"])).status_code == 200
    assert client.post("/v1/progress", headers=device(a["device_token"]),
                       json={"events": [event]}).json() == {"accepted": 1}


def test_rejected_auth_is_logged_without_tokens(caplog):
    caplog.set_level(logging.INFO)
    client, _ = v2_client()
    p = client.post("/v1/devices/pair", json={"session_id": sid()}).json()
    client.get("/v1/devices", headers={"authorization": "Bearer secret-wrong-portal-token"})
    client.get("/v1/devices/me", headers={"authorization": "Bearer secret-wrong-device-token"})
    client.get("/v1/devices/me", headers=device(p["device_token"]))
    assert any("portal auth rejected" in m for m in caplog.messages)
    assert any("device auth rejected" in m for m in caplog.messages)
    text = caplog.text
    for secret in ("secret-wrong-portal-token", "secret-wrong-device-token", p["device_token"], PORTAL_TOKEN):
        assert secret not in text
