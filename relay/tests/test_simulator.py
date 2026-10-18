"""Browser simulation uses portal auth and the same verified ask pipeline as the lens."""
from _relay_helpers import PORTAL, device, sid, v2_client
from specs_relay import org


def test_simulator_requires_portal_auth_and_reuses_verified_answers():
    client, _ = v2_client()
    question = {"session_id": sid(), "text": "how tight is the m5"}
    assert client.post("/v1/simulator/ask", json=question).status_code == 401
    response = client.post("/v1/simulator/ask", headers=PORTAL, json=question)
    assert response.status_code == 200
    assert response.json()["verified"] is True
    assert response.json()["outcome"] == "answered"


def test_simulator_asks_run_in_the_portals_workspace(monkeypatch):
    client, app = v2_client()
    ws = client.post("/v1/orgs", json={"name": "Simulator workshop"}).json()
    seen = []
    original = app.state.pipeline.retriever.retrieve

    async def retrieve(*args, **kwargs):
        seen.append(org.current())
        return await original(*args, **kwargs)

    monkeypatch.setattr(app.state.pipeline.retriever, "retrieve", retrieve)
    response = client.post("/v1/simulator/ask", headers=device(ws["join_code"]),
                           json={"session_id": sid(), "text": "how tight is the m5"})
    assert response.status_code == 200
    assert seen == [ws["org_id"]]
    assert app.state.pipeline.db.devices == {}  # no synthetic worker created


def test_simulator_diagrams_require_approval_and_workspace_ownership(monkeypatch):
    client, app = v2_client()
    assert client.get("/v1/simulator/diagrams/DGM-1").status_code == 401
    seen = []

    async def diagram(diagram_id, approved_only=True):
        seen.append(approved_only)
        return {"doc_id": "SOP-900", "revision": "A", "tiles": [b"pixels", b"pixels"]}

    async def foreign_procedures():
        return [{"doc_id": "SOP-901", "revision": "A", "title": "Other procedure", "status": "effective"}]

    monkeypatch.setattr(app.state.pipeline.db, "get_diagram", diagram)
    monkeypatch.setattr(app.state.pipeline.db, "list_procedures", foreign_procedures)
    assert client.get("/v1/simulator/diagrams/DGM-1", headers=PORTAL).status_code == 404
    assert seen == [True]


def test_simulator_walkthrough_can_fetch_its_approved_diagram():
    client, _ = v2_client()
    response = client.post("/v1/simulator/ask", headers=PORTAL,
                           json={"session_id": sid(), "text": "walk me through the bracket"})
    steps = response.json()["walkthrough"]["steps"]
    diagram = next(step["diagram"]["diagram_id"] for step in steps if step.get("diagram"))
    result = client.get(f"/v1/simulator/diagrams/{diagram}", headers=PORTAL)
    assert result.status_code == 200
    assert [tile["slot"] for tile in result.json()["tiles"]] == [0, 1]
