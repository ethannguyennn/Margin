"""v2 routes (BUILD-PLAN-V2 section 5) on the mock relay: every route answers with a
schema-valid response, and the M3 flow runs end to end on mocks."""

from __future__ import annotations

import base64
import io

import pytest
from pydantic import ValidationError

from _relay_helpers import PORTAL, ask, device, pair_and_claim, sid, v2_client, wait_material
from margin_relay.schemas import (
    ApproveResult,
    Assignment,
    AskResponse,
    BoardRow,
    DiagramImage,
    DeviceInfo,
    DraftStep,
    Latency,
    MaterialStatus,
    MaterialText,
    Pairing,
    ProcedureDraft,
)

SOP_150 = (b"WARNING: Isolate power before opening the housing.\n\n"
           b"1. Remove the four gland nuts with a 10 mm socket.\n"
           b"2. Torque the four gland nuts to 6 N-m in a star pattern.\n")


def _upload(client, data=SOP_150, name="SOP-150.md", **fields):
    form = {"doc_id": "SOP-150", "revision": "A", "title": "Pump seal swap", **fields}
    return client.post("/v1/materials", headers=PORTAL, files={"file": (name, data)}, data=form)


# --- the M3 flow, end to end on mocks ------------------------------------------------


def test_m3_upload_review_approve_pair_assign_step_through_and_board():
    client, app = v2_client()
    with client:
        # 1. supervisor uploads; conversion runs in the background
        created = _upload(client)
        assert created.status_code == 202
        material_id = created.json()["material_id"]
        assert MaterialStatus.model_validate(wait_material(client, material_id)).status == "ready"
        MaterialText.model_validate(client.get(f"/v1/materials/{material_id}/text", headers=PORTAL).json())
        draft = ProcedureDraft.model_validate(client.get("/v1/drafts/SOP-150/A", headers=PORTAL).json())
        step2 = draft.steps[1]
        assert step2.diagram is not None and step2.diagram_id and not step2.diagram_approved

        # 2. the lens-exact preview is reviewable before approval
        preview = client.get(f"/v1/diagrams/{step2.diagram_id}/preview.png", headers=PORTAL)
        assert preview.status_code == 200 and preview.headers["content-type"] == "image/png"
        assert preview.content[:8] == b"\x89PNG\r\n\x1a\n"

        # 3. approve is refused until the diagram is approved
        refused = client.post("/v1/drafts/SOP-150/A/approve", headers=PORTAL)
        assert refused.status_code == 409
        assert refused.json()["detail"] == [{"label": "2", "reason": "diagram needs approval or detachment"}]
        assert client.post(f"/v1/drafts/SOP-150/A/diagrams/{step2.diagram_id}/approve",
                           headers=PORTAL).json() == {"ok": True}

        # 4. publish
        published = client.post("/v1/drafts/SOP-150/A/approve", headers=PORTAL)
        assert published.status_code == 200, published.text
        result = ApproveResult.model_validate(published.json())
        assert [s.step_id for s in result.steps] == ["SOP-150:A:1", "SOP-150:A:2"]
        assert result.steps[1].diagram.diagram_id == step2.diagram_id
        procedures = client.get("/v1/procedures").json()
        assert {"doc_id": "SOP-150", "title": "Pump seal swap", "revision": "A", "status": "effective"} in procedures

        # 5. pair the lens, claim it in the portal, assign the task
        lens = pair_and_claim(client, "Bay 3")
        Pairing.model_validate(lens)
        [DeviceInfo.model_validate(d) for d in client.get("/v1/devices", headers=PORTAL).json()]
        assigned = client.post("/v1/assignments", headers=PORTAL,
                               json={"device_id": lens["device_id"], "doc_id": "SOP-150"})
        assert assigned.status_code == 200, assigned.text
        Assignment.model_validate(assigned.json())

        # 6. the lens polls and receives it exactly once
        token = device(lens["device_token"])
        got = client.get("/v1/assignments/next", headers=token)
        assert got.status_code == 200
        task = Assignment.model_validate(got.json())
        assert task.walkthrough.assignment_id == task.assignment_id
        assert task.walkthrough.steps[1].diagram is not None
        assert client.get("/v1/assignments/next", headers=token).status_code == 204

        # 7. "show diagram" -> tiles; progress -> board
        tiles = DiagramImage.model_validate(
            client.get(f"/v1/diagrams/{step2.diagram_id}", headers=token).json())
        assert [t.slot for t in tiles.tiles] == [0, 1]
        assert all((t.width, t.height) == (288, 144) for t in tiles.tiles)
        assert base64.b64decode(tiles.tiles[0].image)[:8] == b"\x89PNG\r\n\x1a\n"
        events = [{"assignment_id": task.assignment_id, "step_id": None, "kind": "task_started", "ts": 1000.0},
                  {"assignment_id": task.assignment_id, "step_id": "SOP-150:A:1", "kind": "step_started", "ts": 1001.0},
                  {"assignment_id": task.assignment_id, "step_id": "SOP-150:A:1", "kind": "step_completed", "ts": 1002.0},
                  {"assignment_id": task.assignment_id, "step_id": "SOP-150:A:2", "kind": "step_started", "ts": 1003.0}]
        assert client.post("/v1/progress", headers=token, json={"events": events}).json() == {"accepted": 4}
        assert client.post("/v1/progress", headers=token, json={"events": events}).json() == {"accepted": 0}
        board = [BoardRow.model_validate(r) for r in client.get("/v1/progress", headers=PORTAL).json()]
    row = next(r for r in board if r.assignment_id == task.assignment_id)
    assert (row.worker_name, row.doc_id, row.step_index, row.total, row.kind) == ("Bay 3", "SOP-150", 2, 2, "step_started")


# --- /v1/ask command fast path -------------------------------------------------------


@pytest.mark.parametrize("phrase,command", [("next", "next"), ("okay done", "next"), ("go back", "back"),
                                            ("show diagram", "diagram"), ("pause", "pause"),
                                            ("close margin", "exit")])
def test_command_never_touches_retrieval_or_the_llm(phrase, command):
    client, app = v2_client()
    p = app.state.pipeline
    b = ask(client, phrase, context={"doc_id": "SOP-114", "step_id": "SOP-114:C:4.2",
                                     "assignment_id": "ASN-0001"}).json()
    assert (b["outcome"], b["intent"], b["command"]) == ("command", "command", command)
    assert (b["glance"], b["body"], b["citations"], b["verified"]) == ("", "", [], False)
    assert p.retriever.calls == 0 and p.generator.calls == 0
    lat = b["latency_ms"]
    assert lat["embed"] == lat["retrieve"] == lat["generate"] == lat["verify"] == 0
    event = p.db.events[-1]
    assert (event["intent"], event["outcome"], event["doc_ids"]) == ("command", "command", ["SOP-114"])
    assert event["assignment_id"] == "ASN-0001"  # recorded once the writer accepts it


def test_command_relay_time_is_stt_plus_under_50ms():
    client, _ = v2_client()
    pcm = base64.b64encode(b"\x00\x00" * 16000).decode()

    class SaysNext:
        async def transcribe(self, pcm, sample_rate):
            return "next"

    client.app.state.pipeline.transcriber = SaysNext()
    b = client.post("/v1/ask", json={"session_id": sid(), "context": {"doc_id": "SOP-114", "step_id": "SOP-114:C:4.1"},
                                     "audio": {"format": "pcm_s16le", "sample_rate": 16000, "channels": 1,
                                               "data_b64": pcm}}).json()
    assert b["command"] == "next"
    assert b["latency_ms"]["total"] - b["latency_ms"]["stt"] < 50


def test_repeat_is_a_command_only_inside_a_task():
    client, app = v2_client()
    s = sid()
    inside = ask(client, "say that again", s, context={"doc_id": "SOP-114", "step_id": "SOP-114:C:4.2"}).json()
    assert inside["outcome"] == "command" and inside["command"] == "repeat"
    outside = ask(client, "say that again", s).json()
    assert outside["intent"] == "repeat" and outside["outcome"] == "not_found"  # v1: nothing to replay yet
    ask(client, "how tight is the m5 on the mounting bracket", s)
    replay = ask(client, "repeat", s).json()
    assert replay["intent"] == "repeat" and replay["outcome"] == "answered" and replay["command"] is None


@pytest.mark.parametrize("text", ["what's the next step's torque", "go back to the torque value",
                                  "show me the M5 spec", "is this step done right"])
def test_near_miss_phrases_are_questions_not_commands(text):
    client, _ = v2_client()
    b = ask(client, text, context={"doc_id": "SOP-114", "step_id": "SOP-114:C:4.2"}).json()
    assert b["outcome"] != "command" and b["command"] is None


def test_command_response_contract():
    base = dict(trace_id="t", transcript="next", intent="command", source="", citations=[],
                latency_ms=Latency())
    AskResponse(outcome="command", command="next", glance="", body="", verified=False, **base)
    for bad in ({"command": None}, {"glance": "x"}, {"verified": True}):
        with pytest.raises(ValidationError):
            AskResponse(**{**dict(outcome="command", command="next", glance="", body="", verified=False, **base), **bad})
    with pytest.raises(ValidationError):  # command only with outcome command
        AskResponse(outcome="not_found", command="next", glance="x", body="y", verified=False, **base)


def test_walk_me_through_carries_v2_step_extras():
    client, _ = v2_client()
    w = ask(client, "walk me through the bracket assembly").json()["walkthrough"]
    steps = {s["label"]: s for s in w["steps"]}
    assert steps["4.1"]["warning"] == "Isolate power before assembly."
    assert steps["4.3"]["checkpoint"] == "0.20 mm gauge must not enter"
    assert steps["4.2"]["diagram"] == {"diagram_id": "DGM-0001", "width": 576, "height": 144,
                                       "alt": "Star pattern: upper left, lower right, upper right, lower left"}


# --- drafts: edits are re-verified, approval is gated --------------------------------


def _converted(client):
    _upload(client)
    assert wait_material(client, "MAT-0001")["status"] == "ready"


def test_edit_is_reverified_on_every_save_and_detach_works():
    client, _ = v2_client()
    with client:
        _converted(client)
        path = "/v1/drafts/SOP-150/A/steps/2"
        bad = client.put(path, headers=PORTAL, json={"body": "Torque the four gland nuts to 5 N-m."})
        assert bad.status_code == 200
        step = DraftStep.model_validate(bad.json())
        assert step.verify.ok is False and "5" in step.verify.reason
        refused = client.post("/v1/drafts/SOP-150/A/approve", headers=PORTAL)
        assert refused.status_code == 409
        assert {"label": "2", "reason": step.verify.reason} in refused.json()["detail"]
        good = DraftStep.model_validate(client.put(path, headers=PORTAL, json={
            "body": "Torque the four gland nuts to 6 N-m in a star pattern."}).json())
        assert good.verify.ok and good.diagram_id  # an untouched diagram stays attached
        detached = DraftStep.model_validate(client.put(path, headers=PORTAL, json={
            "glance": good.glance, "body": good.body, "warning": None, "checkpoint": None,
            "diagram": None, "diagram_id": None}).json())
        assert detached.diagram is None and detached.diagram_id is None and detached.verify.ok
        ok = client.post("/v1/drafts/SOP-150/A/approve", headers=PORTAL)
        assert ok.status_code == 200 and ok.json()["steps"][1]["diagram"] is None
        again = client.put(path, headers=PORTAL, json={"body": "anything"})
        assert again.status_code == 409  # published revisions are immutable


def test_over_cap_edit_fails_verification_instead_of_raising():
    client, _ = v2_client()
    with client:
        _converted(client)
        r = client.put("/v1/drafts/SOP-150/A/steps/1", headers=PORTAL, json={"warning": "w" * 81})
    assert r.status_code == 200 and "warning is 81 chars" in r.json()["verify"]["reason"]


def test_diagram_approval_requires_a_verified_step_and_the_right_draft():
    client, _ = v2_client()
    with client:
        _converted(client)
        client.put("/v1/drafts/SOP-150/A/steps/2", headers=PORTAL, json={"body": "6 N-m and 9 N-m"})
        diagram_id = client.get("/v1/drafts/SOP-150/A", headers=PORTAL).json()["steps"][1]["diagram_id"]
        r = client.post(f"/v1/drafts/SOP-150/A/diagrams/{diagram_id}/approve", headers=PORTAL)
        assert r.status_code == 409 and "Verify the step" in r.json()["error"]["message"]
        assert client.post(f"/v1/drafts/SOP-999/A/diagrams/{diagram_id}/approve", headers=PORTAL).status_code == 404


def test_lens_never_sees_a_draft_or_unknown_diagram():
    client, _ = v2_client()
    with client:
        _converted(client)
        lens = pair_and_claim(client)
        diagram_id = client.get("/v1/drafts/SOP-150/A", headers=PORTAL).json()["steps"][1]["diagram_id"]
        assert client.get(f"/v1/diagrams/{diagram_id}", headers=device(lens["device_token"])).status_code == 404
        assert client.get("/v1/diagrams/DGM-9999", headers=device(lens["device_token"])).status_code == 404
        demo = client.get("/v1/diagrams/DGM-0001", headers=device(lens["device_token"]))
    assert demo.status_code == 200  # the approved demo diagram on SOP-114 rev C


def test_missing_draft_and_step_are_404():
    client, _ = v2_client()
    assert client.get("/v1/drafts/SOP-404/A", headers=PORTAL).status_code == 404
    assert client.post("/v1/drafts/SOP-404/A/approve", headers=PORTAL).status_code == 404
    assert client.get("/v1/materials/MAT-9999", headers=PORTAL).status_code == 404


# --- uploads are validated before anything is stored ---------------------------------


@pytest.mark.parametrize("data,name,status", [
    (b"MZ\x90\x00binary", "tool.exe", 415),
    (b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, "SOP-150.pdf", 415),  # contents do not match the extension
    (b"PK\x03\x04not a real zip", "SOP-150.docx", 415),
    (b"", "empty.md", 400),
])
def test_wrong_type_or_empty_upload_is_rejected_before_storage(data, name, status):
    client, app = v2_client()
    r = _upload(client, data, name)
    assert r.status_code == status, r.text
    assert app.state.pipeline.db.materials == {}


def test_oversized_upload_is_rejected_before_storage():
    client, app = v2_client(max_upload_mb=1)
    r = _upload(client, b"x" * (1024 * 1024 + 10), "big.txt")
    assert r.status_code == 413 and app.state.pipeline.db.materials == {}


@pytest.mark.parametrize("field,value", [("doc_id", "sop-150"), ("doc_id", "SOP-15"), ("revision", "AB-1"),
                                         ("title", "x" * 121), ("title", "")])
def test_bad_identifiers_are_rejected_before_storage(field, value):
    client, app = v2_client()
    r = _upload(client, **{field: value})
    assert r.status_code == 400 and app.state.pipeline.db.materials == {}


def test_real_docx_and_images_are_accepted_by_magic_bytes():
    import zipfile

    client, app = v2_client()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
    with client:
        assert _upload(client, buf.getvalue(), "SOP-151.docx", doc_id="SOP-151").status_code == 202
        assert _upload(client, b"\xff\xd8\xff\xe0jpegdata", "SOP-152.jpg", doc_id="SOP-152").status_code == 202
        mimes = sorted(m["mime"] for m in app.state.pipeline.db.materials.values())
    assert mimes == ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", "image/jpeg"]


# --- assignments + progress ----------------------------------------------------------


def test_assign_unknown_device_or_procedure_is_404():
    client, _ = v2_client()
    lens = pair_and_claim(client)
    assert client.post("/v1/assignments", headers=PORTAL,
                       json={"device_id": "LNS-9999", "doc_id": "SOP-114"}).status_code == 404
    assert client.post("/v1/assignments", headers=PORTAL,
                       json={"device_id": lens["device_id"], "doc_id": "SOP-404"}).status_code == 404
    unclaimed = client.post("/v1/devices/pair", json={"session_id": sid()}).json()
    assert client.post("/v1/assignments", headers=PORTAL,
                       json={"device_id": unclaimed["device_id"], "doc_id": "SOP-114"}).status_code == 404


def test_large_offline_batches_are_split_and_idempotent():
    client, app = v2_client()
    lens = pair_and_claim(client)
    a = client.post("/v1/assignments", headers=PORTAL, json={"device_id": lens["device_id"], "doc_id": "SOP-114"}).json()
    events = [{"assignment_id": a["assignment_id"], "step_id": "SOP-114:C:4.1", "kind": "step_started",
               "ts": 1000.0 + i} for i in range(250)]
    token = device(lens["device_token"])
    assert client.post("/v1/progress", headers=token, json={"events": events}).json() == {"accepted": 250}
    assert client.post("/v1/progress", headers=token, json={"events": events}).json() == {"accepted": 0}
    assert len(app.state.pipeline.db.progress) == 250


def test_task_completed_drops_the_row_from_the_board():
    client, _ = v2_client()
    lens = pair_and_claim(client)
    a = client.post("/v1/assignments", headers=PORTAL, json={"device_id": lens["device_id"], "doc_id": "SOP-114"}).json()
    assert len(client.get("/v1/progress", headers=PORTAL).json()) == 1
    client.post("/v1/progress", headers=device(lens["device_token"]), json={"events": [
        {"assignment_id": a["assignment_id"], "step_id": None, "kind": "task_completed", "ts": 5000.0}]})
    assert client.get("/v1/progress", headers=PORTAL).json() == []


def test_portal_errors_carry_a_readable_detail():
    client, _ = v2_client()
    r = client.post("/v1/devices/claim", headers=PORTAL, json={"pair_code": "ABCD", "worker_name": "x"})
    b = r.json()
    assert r.status_code == 404 and b["error"]["code"] == "not_found" and b["trace_id"]
    assert b["detail"] == b["error"]["message"]
