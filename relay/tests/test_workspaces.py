"""Workspaces: the admin's code opens the portal, a lens joins with that code, and
every SOP read is scoped to the lens's workspace. All on the mock relay."""

from __future__ import annotations

import contextvars

from _relay_helpers import PORTAL, device, sid, v2_client
from specs_relay import db, org


def _workspace(client, name="Acme Line 3") -> dict:
    r = client.post("/v1/orgs", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()


def _lens(client) -> dict:
    return client.post("/v1/devices/pair", json={"session_id": sid()}).json()


def test_create_workspace_returns_a_code_that_opens_the_portal():
    client, _ = v2_client()
    ws = _workspace(client)
    assert len(ws["join_code"]) == 6 and ws["name"] == "Acme Line 3"
    me = client.get("/v1/orgs/me", headers=device(ws["join_code"].lower()))
    assert me.status_code == 200 and me.json() == ws
    assert client.get("/v1/orgs/me", headers=PORTAL).json()["org_id"] == org.DEFAULT_ORG


def test_lens_joins_with_the_code_and_shows_as_claimed():
    client, _ = v2_client()
    ws = _workspace(client)
    lens = _lens(client)
    r = client.post("/v1/devices/join", headers=device(lens["device_token"]),
                    json={"code": f" {ws['join_code'].lower()} ", "worker_name": "Maria"})
    assert r.status_code == 200, r.text
    joined = r.json()
    assert joined["claimed"] is True and joined["worker_name"] == "Maria"
    assert joined["workspace"] == "Acme Line 3" and joined["device_token"] == lens["device_token"]
    me = client.get("/v1/devices/me", headers=device(lens["device_token"])).json()
    assert me["claimed"] is True and me["workspace"] == "Acme Line 3"


def test_join_needs_a_known_code_and_a_paired_lens():
    client, _ = v2_client()
    lens = _lens(client)
    r = client.post("/v1/devices/join", headers=device(lens["device_token"]), json={"code": "NOPE42"})
    assert r.status_code == 404
    assert client.post("/v1/devices/join", json={"code": "DEMO"}).status_code == 401


def test_portal_sees_only_its_workspaces_devices():
    client, _ = v2_client()
    ws = _workspace(client)
    lens = _lens(client)
    client.post("/v1/devices/join", headers=device(lens["device_token"]), json={"code": ws["join_code"]})
    mine = client.get("/v1/devices", headers=device(ws["join_code"])).json()
    assert [d["device_id"] for d in mine] == [lens["device_id"]]
    assert client.get("/v1/devices", headers=PORTAL).json() == []  # the demo workspace


def test_procedures_follow_the_lens_workspace():
    client, app = v2_client()
    ws = _workspace(client)
    mdb = app.state.pipeline.db
    mdb.doc_orgs["SOP-114"] = ws["org_id"]
    acme, demo = _lens(client), _lens(client)
    client.post("/v1/devices/join", headers=device(acme["device_token"]), json={"code": ws["join_code"]})
    client.post("/v1/devices/join", headers=device(demo["device_token"]), json={"code": "DEMO"})
    docs = lambda lens: {p["doc_id"] for p in client.get(  # noqa: E731
        "/v1/procedures", headers=device(lens["device_token"])).json()}
    assert "SOP-114" in docs(acme) and "SOP-114" not in docs(demo)
    unscoped = {p["doc_id"] for p in client.get("/v1/procedures").json()}
    assert "SOP-114" in unscoped  # no device token: every workspace, as before


def test_sop_reads_filter_on_the_current_workspace():
    def clause(org_id):
        org.use(org_id)
        return db._revision_clause(None)

    run = lambda org_id: contextvars.copy_context().run(clause, org_id)  # noqa: E731
    assert run(None) == ("d.status = 'effective'", ())
    assert run("ORG-0001") == ("d.status = 'effective' AND d.org_id = %s", ("ORG-0001",))
