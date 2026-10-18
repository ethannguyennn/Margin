"""Structuring + verify + one retry, with a scripted structurer (no network).

The MaterialText is hand-written (tests/test_verify_step.py); real Gemini
conversions are exercised by eval/conversion/run_conversion_eval.py.
"""

import asyncio
import copy
import io
import json
from types import SimpleNamespace as NS

import pytest
from PIL import Image

from margin_relay.convert import structure as S
from test_verify_step import MATERIAL

GOOD_STEP = {
    "label": "4",
    "glance": "Torque M6 gland nuts to 4 N-m",
    "body": "Torque the M6 gland nuts to 4 N-m in a star pattern.",
    "warning": "",
    "checkpoint": "",
    "quotes": ["Torque the M6 gland nuts to 4 N-m in a star pattern"],
    "diagram": {"kind": "crop", "figure_id": "F1", "box_2d": [0, 500, 1000, 1000], "alt": "Nut order"},
}
GAP_STEP = {
    "label": "5",
    "glance": "Check gap with 0.20 mm gauge",
    "body": "Check the gap under the gland plate with a 0.20 mm feeler gauge.",
    "warning": "",
    "checkpoint": "0.20 mm gauge must not enter",
    "quotes": ["Check the gap under the gland plate with a 0.20 mm feeler gauge. The gauge must not enter."],
    "diagram": {"kind": "none"},
}


def hallucinate(step):
    """The forced hallucination: 4 N-m becomes 5 N-m in the text, never in the quotes."""
    s = copy.deepcopy(step)
    s["glance"] = s["glance"].replace("4 N-m", "5 N-m")
    s["body"] = s["body"].replace("4 N-m", "5 N-m")
    return s


class Scripted:
    def __init__(self, *outputs):
        self.outputs, self.prompts, self.images = list(outputs), [], []

    async def call(self, prompt, images):
        self.prompts.append(prompt)
        self.images.append(images)
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out

    @property
    def calls(self):
        return len(self.prompts)


def convert(structurer, material=MATERIAL, images=None):
    return asyncio.run(S.convert_dict(material, "SOP-150", "A", "Pump seal swap", structurer, images))


def test_good_conversion_verifies_and_maps_the_crop():
    st = Scripted({"steps": [GOOD_STEP, GAP_STEP], "warnings": []})
    draft = convert(st)
    assert st.calls == 1
    assert draft["status"] == "ready" and draft["material_id"] == "mat-150"
    s4, s5 = draft["steps"]
    assert s4["verify"] == {"ok": True, "reason": None, "citations": []}
    assert s5["verify"]["ok"] and s5["checkpoint"] == "0.20 mm gauge must not enter"
    assert s4["warning"] is None and s5["diagram"] is None
    # right half of figure F1 (page box 0.55..0.95 x 0.20..0.60) -> page coordinates
    assert s4["diagram"]["bbox"] == (0.75, 0.2, 0.95, 0.6)
    assert s4["diagram_approved"] is False and s4["diagram_id"] is None


def test_forced_hallucination_is_caught_retried_once_and_kept_failing():
    bad = hallucinate(GOOD_STEP)
    st = Scripted({"steps": [bad, GAP_STEP], "warnings": []}, {"steps": [bad], "warnings": []})
    draft = convert(st)
    assert st.calls == 2
    labels = [s["label"] for s in draft["steps"]]
    assert labels == ["4", "5"]                      # never dropped
    s4 = draft["steps"][0]
    assert s4["verify"]["ok"] is False
    assert "body says 5 N-m; no quote contains 5 N-m" in s4["verify"]["reason"]
    assert "glance says 5 N-m; no quote contains 5 N-m" in s4["verify"]["reason"]
    # the retry asked only about the failing step, with its reasons
    assert "step 4: " in st.prompts[1] and "step 5: " not in st.prompts[1]
    assert "body says 5 N-m" in st.prompts[1]


def test_retry_can_fix_a_step():
    st = Scripted({"steps": [hallucinate(GOOD_STEP), GAP_STEP], "warnings": []},
                  {"steps": [GOOD_STEP], "warnings": []})
    draft = convert(st)
    assert all(s["verify"]["ok"] for s in draft["steps"])


def test_passing_steps_are_not_retried_or_replaced():
    other = dict(GAP_STEP, glance="Check gap with 0.25 mm gauge")
    st = Scripted({"steps": [hallucinate(GOOD_STEP), GAP_STEP], "warnings": []},
                  {"steps": [GOOD_STEP, other], "warnings": []})
    draft = convert(st)
    assert draft["steps"][1]["glance"] == "Check gap with 0.20 mm gauge"


def test_retry_failure_keeps_the_failing_step():
    st = Scripted({"steps": [hallucinate(GOOD_STEP)], "warnings": []}, S.StructureError("timed out"))
    draft = convert(st)
    assert [s["verify"]["ok"] for s in draft["steps"]] == [False]


def test_unit_conversion_fails_verification():
    conv = dict(GOOD_STEP, body="Torque the M6 gland nuts to 35 in-lb in a star pattern.")
    st = Scripted({"steps": [conv], "warnings": []}, {"steps": [conv], "warnings": []})
    reason = convert(st)["steps"][0]["verify"]["reason"]
    assert "body says 35 in-lb; no quote contains 35 in-lb" in reason


def test_fields_are_sanitized_for_the_lens():
    s = dict(GOOD_STEP, glance="Torque M6 nuts to 4 N·m ✅", diagram={"kind": "none"})
    draft = convert(Scripted({"steps": [s], "warnings": []}))
    assert draft["steps"][0]["glance"] == "Torque M6 nuts to 4 N-m"


def test_document_warnings_must_be_verbatim():
    st = Scripted({"steps": [GOOD_STEP], "warnings": [
        "WARNING: Isolate power and drain the pump before opening the seal housing.",
        "Wear hearing protection at all times."]})
    assert convert(st)["warnings"] == ["WARNING: Isolate power and drain the pump before opening the seal housing."]


def test_schematic_step_passes_with_quoted_labels():
    s = dict(GOOD_STEP, diagram={"kind": "schematic", "alt": "Star order", "elements": [
        {"type": "callout", "x": 60, "y": 30, "r": 15, "label": "1"},
        {"type": "text", "x": 300, "y": 60, "label": "4 N-m"}]})
    step = convert(Scripted({"steps": [s], "warnings": []}))["steps"][0]
    assert step["verify"]["ok"]
    assert step["diagram"]["elements"][1] == {"type": "text", "x": 300, "y": 60, "x2": None, "y2": None,
                                              "r": None, "label": "4 N-m"}


def test_no_steps_is_a_failed_draft():
    assert convert(Scripted({"steps": [], "warnings": []}))["status"] == "failed"


# --- chunking ---------------------------------------------------------------------------

def test_chunk_pages_overlap_by_one_page():
    pages = [{"page": i, "text": "x" * 400} for i in range(1, 6)]
    groups = S.chunk_pages(pages, limit=1000)
    assert [[p["page"] for p in g] for g in groups] == [[1, 2], [2, 3], [3, 4], [4, 5]]


def test_long_material_seam_and_duplicate_labels():
    long = {"material_id": "m", "figures": [],
            "pages": [{"page": 1, "text": MATERIAL["pages"][0]["text"] + "a" * S.CHUNK_CHARS},
                      {"page": 2, "text": MATERIAL["pages"][1]["text"]}]}
    plain = dict(GOOD_STEP, diagram={"kind": "none"})  # this material has no figures
    st = Scripted({"steps": [plain], "warnings": []},
                  {"steps": [plain, GAP_STEP], "warnings": []})
    draft = convert(st, long)
    assert st.calls == 2 and all(s["verify"]["ok"] for s in draft["steps"])
    assert "the last one is 4: Torque M6 gland nuts to 4 N-m" in st.prompts[1]
    assert [s["label"] for s in draft["steps"]] == ["4", "5"]


# --- request shape (fake client) --------------------------------------------------------

class FakeModels:
    def __init__(self, payload, delay=0.0):
        self.payload, self.delay, self.requests = payload, delay, []

    async def generate_content(self, *, model, contents, config):
        self.requests.append(NS(model=model, contents=contents, config=config))
        await asyncio.sleep(self.delay)
        return NS(text=json.dumps(self.payload))


def test_structurer_request_carries_rules_schema_and_figures():
    models = FakeModels({"steps": [GOOD_STEP], "warnings": []})
    st = S.GeminiStructurer(NS(aio=NS(models=models)), "model-from-config")
    asyncio.run(S.convert_dict(MATERIAL, "SOP-150", "A", "t", st, {"F1": b"\x89PNG"}))
    req = models.requests[0]
    assert req.model == "model-from-config"
    assert req.config.response_json_schema == S.RESPONSE_SCHEMA
    assert req.config.temperature <= 0.2
    for rule in ["Use ONLY the provided MATERIAL", "Never add steps, values, tools or warnings",
                 "One physical action per step", "shortened only by deletion", "measurable acceptance check",
                 "verbatim spans copied from MATERIAL", "Never convert units", "kind:'schematic'"]:
        assert rule in req.config.system_instruction
    assert req.contents[0] == "FIGURE F1 image:"
    assert req.contents[1].inline_data.mime_type == "image/png"
    assert "=== PAGE 1 ===" in req.contents[-1] and "FIGURE F1 (page 1)" in req.contents[-1]


def test_structurer_timeout_is_typed():
    st = S.GeminiStructurer(NS(aio=NS(models=FakeModels({}, delay=0.5))), "m", timeout=0.01)
    with pytest.raises(S.StructureError):
        asyncio.run(st.call("p", {}))


def test_figure_images_crop_each_figure():
    page = Image.new("L", (1000, 500), 255)
    buf = io.BytesIO()
    page.save(buf, "PNG")
    out = S.figure_images({1: buf.getvalue()}, MATERIAL["figures"])
    assert Image.open(io.BytesIO(out["F1"])).size == (400, 200)
