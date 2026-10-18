"""The conversion job (README-PART-3 section 6), on the mock relay."""

from __future__ import annotations

import asyncio

from _relay_helpers import PORTAL, v2_client, wait_material
from specs_relay.jobs import JobRunner, readable
from specs_relay.main import build_pipeline
from specs_relay.pipeline import ConversionError, mock
from _relay_helpers import make_settings

SOP_153 = b"""# SOP-153 Quick start

WARNING: Wear safety glasses.

1. Close the inlet valve fully.
2. Torque the four cover bolts to 6 N-m in a star pattern.
3. Open the valve and check for leaks. No drip is allowed.
"""


def upload(client, data: bytes = SOP_153, name: str = "SOP-153.md", doc_id: str = "SOP-153",
           revision: str = "A", title: str = "Quick start"):
    return client.post("/v1/materials", headers=PORTAL, files={"file": (name, data)},
                       data={"doc_id": doc_id, "revision": revision, "title": title})


def test_text_material_converts_to_a_verified_draft_with_a_rendered_diagram():
    client, app = v2_client()
    with client:
        r = upload(client)
        assert r.status_code == 202 and r.json() == {"material_id": "MAT-0001", "status": "converting"}
        done = wait_material(client, "MAT-0001")
        assert done["status"] == "ready" and done["error"] is None
        text = client.get("/v1/materials/MAT-0001/text", headers=PORTAL).json()
        assert "Torque the four cover bolts to 6 N-m" in text["pages"][0]["text"]
        draft = client.get("/v1/drafts/SOP-153/A", headers=PORTAL).json()
    assert draft["status"] == "ready" and [s["label"] for s in draft["steps"]] == ["1", "2", "3"]
    assert all(s["verify"]["ok"] for s in draft["steps"])
    assert draft["warnings"] == ["WARNING: Wear safety glasses."]
    star = draft["steps"][1]
    assert star["diagram"]["kind"] == "schematic" and star["diagram_id"] == "DGM-0002"
    assert star["diagram_approved"] is False  # conversion never approves a diagram
    stored = app.state.pipeline.db.diagrams["DGM-0002"]
    assert stored["approved"] is False and len(stored["tiles"]) == 2 and stored["preview_png"]


def test_binary_upload_converts_on_mocks_and_says_so():
    client, _ = v2_client()
    pdf = b"%PDF-1.7\n% synthetic\n"
    with client:
        upload(client, pdf, "SOP-150.pdf", "SOP-150", "A", "Pump seal swap")
        assert wait_material(client, "MAT-0001")["status"] == "ready"
        text = client.get("/v1/materials/MAT-0001/text", headers=PORTAL).json()
    assert "MOCK EXTRACTION" in text["pages"][0]["text"]


class Exploding(mock.MockConverter):
    def __init__(self, exc):
        super().__init__()
        self.exc = exc

    async def extract(self, data, mime, material_id):
        raise self.exc


def test_converter_failure_marks_failed_with_a_readable_error():
    client, app = v2_client()
    app.state.pipeline.converter = Exploding(ConversionError("Page 2 could not be read. Upload a clearer scan."))
    with client:
        upload(client)
        done = wait_material(client, "MAT-0001")
    assert done["status"] == "failed" and done["error"] == "Page 2 could not be read. Upload a clearer scan."


def test_unexpected_exception_is_generic_not_a_stack_trace():
    assert readable(RuntimeError("secret internals")) == "Conversion failed (RuntimeError). Upload the file again."

    class Typed(Exception):
        code = "llm_timeout"
    assert readable(Typed("structuring timed out")) == "structuring timed out"


def test_timeout_marks_failed():
    client, app = v2_client(convert_timeout_s=0.05)

    class Slow(mock.MockConverter):
        async def extract(self, data, mime, material_id):
            await asyncio.sleep(5)

    app.state.pipeline.converter = Slow()
    with client:
        upload(client)
        done = wait_material(client, "MAT-0001", timeout=5)
    assert done["status"] == "failed" and "timed out after 0.05 s" in done["error"]


def test_render_failure_fails_the_step_not_the_job():
    client, app = v2_client()

    class Broken(mock.MockRenderer):
        def render(self, spec, page_image):
            raise ValueError("canvas exploded")

    app.state.pipeline.renderer = Broken()
    with client:
        upload(client)
        assert wait_material(client, "MAT-0001")["status"] == "ready"
        star = client.get("/v1/drafts/SOP-153/A", headers=PORTAL).json()["steps"][1]
    assert star["verify"]["ok"] is False and "diagram could not be rendered (canvas exploded)" in star["verify"]["reason"]
    assert star["diagram_id"] is None


def test_material_with_no_steps_fails():
    client, _ = v2_client()
    with client:
        upload(client, b"Just some notes without numbered steps.", "notes.txt")
        done = wait_material(client, "MAT-0001")
    assert done["status"] == "failed" and "No procedure steps" in done["error"]


def test_at_most_two_conversions_run_at_once():
    settings = make_settings(convert_concurrency=2)
    p = build_pipeline(settings)
    running, peak = [0], [0]

    class Counting(mock.MockConverter):
        async def extract(self, data, mime, material_id):
            running[0] += 1
            peak[0] = max(peak[0], running[0])
            await asyncio.sleep(0.05)
            running[0] -= 1
            return await super().extract(data, mime, material_id)

    p.converter = Counting()

    async def scenario():
        jobs = JobRunner(p, settings)
        ids = [await p.db.insert_material("a.md", "text/markdown", SOP_153, f"SOP-15{i}", "A", "t")
               for i in range(5)]
        await asyncio.gather(*(jobs.start(m, SOP_153, "text/markdown", f"SOP-15{i}", "A", "t")
                               for i, m in enumerate(ids)))
        return [p.db.materials[m]["status"] for m in ids]

    assert asyncio.run(scenario()) == ["ready"] * 5
    assert peak[0] == 2


def test_restart_during_conversion_leaves_failed_not_converting():
    client, app = v2_client()
    db = app.state.pipeline.db

    async def stuck():
        return await db.insert_material("a.md", "text/markdown", SOP_153, "SOP-153", "A", "t")

    material_id = asyncio.run(stuck())  # stored as `converting`, no job running: a crashed relay
    assert db.materials[material_id]["status"] == "converting"
    with client:  # boot (lifespan) of the restarted relay
        body = client.get(f"/v1/materials/{material_id}", headers=PORTAL).json()
    assert body["status"] == "failed" and "relay restart" in body["error"]


def test_shutdown_cancels_running_jobs_and_marks_them_failed():
    settings = make_settings()
    p = build_pipeline(settings)

    class Slow(mock.MockConverter):
        async def extract(self, data, mime, material_id):
            await asyncio.sleep(30)

    p.converter = Slow()

    async def scenario():
        jobs = JobRunner(p, settings)
        mid = await p.db.insert_material("a.md", "text/markdown", SOP_153, "SOP-153", "A", "t")
        jobs.start(mid, SOP_153, "text/markdown", "SOP-153", "A", "t")
        await asyncio.sleep(0.01)
        await jobs.shutdown()
        return p.db.materials[mid]

    m = asyncio.run(scenario())
    assert m["status"] == "failed" and "shut down" in m["error"]
