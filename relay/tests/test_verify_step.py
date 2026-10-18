"""Draft-step verifier test matrix. Hand-written MaterialText, no LLM.

These fixtures are synthetic and hand-written; they are not converter output.
"""

import pytest

from margin_relay.convert.verify_step import step_failures, verify_step

PAGE_1 = """# SOP-150 Pump seal swap

> WARNING: Isolate power and drain the pump before opening the seal housing.
> Do not reuse the old O-ring.

## 4 Procedure
1. Remove the four M6 gland nuts with a 10 mm socket.
2. Lift the gland plate and discard the old O-ring (HX2-311).
3. Fit the new O-ring dry. Do not lubricate the O-ring.
4. Torque the M6 gland nuts to 4 N-m in a star pattern: upper left, lower right,
   upper right, lower left.
5. Check the gap under the gland plate with a 0.20 mm feeler gauge. The gauge must not enter.
"""
PAGE_2 = """6. Run the pump for 30 s at 1200 rpm and check for leaks.
Seal kit lot number: [illegible]
"""
MATERIAL = {
    "material_id": "mat-150",
    "pages": [{"page": 1, "text": PAGE_1}, {"page": 2, "text": PAGE_2},
              {"page": 3, "text": "[page 3 failed to read]"}],
    "figures": [{"figure_id": "F1", "page": 1, "bbox": (0.55, 0.20, 0.95, 0.60),
                 "caption": "Figure 1: exploded view of the seal housing"}],
}

Q4 = "Torque the M6 gland nuts to 4 N-m in a star pattern"


def step(**kw):
    base = {
        "label": "4",
        "glance": "Torque M6 gland nuts to 4 N-m",
        "body": "Torque the M6 gland nuts to 4 N-m in a star pattern.",
        "warning": None,
        "checkpoint": None,
        "quotes": [Q4],
        "diagram": None,
        "diagram_id": None,
        "diagram_approved": False,
    }
    base.update(kw)
    return base


def reasons(**kw):
    return step_failures(step(**kw), MATERIAL)


# --- README-PART-4 section 6 matrix ------------------------------------------

def test_verbatim_quote_passes():
    assert reasons() == []


def test_whitespace_and_case_variation_passes():
    assert reasons(quotes=["torque THE m6 gland nuts   to 4 N-m\nin a star pattern"]) == []


def test_hallucinated_quote_fails():
    r = reasons(quotes=["Torque the M6 gland nuts to 4 N-m with thread locker applied"])
    assert len(r) == 1 and r[0].startswith("quote 1 is not in the material")


def test_torque_changed_in_body_fails_readably():
    r = reasons(body="Torque the M6 gland nuts to 5 N-m in a star pattern.")
    assert r == ["body says 5 N-m; no quote contains 5 N-m"]


def test_unit_converted_fails():
    r = reasons(body="Torque the M6 gland nuts to 35 in-lb in a star pattern.")
    assert r == ["body says 35 in-lb; no quote contains 35 in-lb"]


def test_warning_not_in_source_fails():
    r = reasons(warning="Wear safety glasses.",
                quotes=[Q4, "Isolate power and drain the pump before opening the seal housing."])
    assert r == ["warning is not the material's own warning text"]


def test_schematic_label_absent_from_quotes_fails():
    spec = {"kind": "schematic", "alt": "Star order for the gland nuts",
            "elements": [{"type": "callout", "x": 100, "y": 40, "r": 14, "label": "1"},
                         {"type": "text", "x": 300, "y": 100, "label": "6 Nm"}]}
    r = reasons(diagram=spec)
    assert r == ["diagram label says 6 Nm; no quote contains 6 Nm"]


def test_illegible_region_quoted_fails():
    r = reasons(glance="Record the seal kit lot", body="Record the seal kit lot number.",
                quotes=["Seal kit lot number: [illegible]"])
    assert r == ["quote 1 relies on text marked [illegible]"]


# --- the rest of the rules ---------------------------------------------------------

def test_quote_from_a_page_that_failed_to_read_fails():
    r = reasons(quotes=[Q4, "[page 3 failed to read]"])
    assert r == ["quote 2 relies on a page that failed to read"]


def test_quote_may_span_a_page_break():
    r = reasons(glance="Check the gap, then run 30 s", body="Check the gap, then run the pump for 30 s.",
                quotes=["The gauge must not enter. 6. Run the pump for 30 s"])
    assert r == []


def test_step_without_quotes_fails():
    assert reasons(quotes=[]) == ["no quotes: every step needs source quotes"]


def test_warning_shortened_by_deletion_passes():
    w = "Isolate power and drain the pump before opening the housing."
    assert reasons(warning=w, quotes=[Q4, "WARNING: Isolate power and drain the pump before "
                                          "opening the seal housing."]) == []


def test_warning_that_deletes_a_negation_fails():
    r = reasons(glance="Fit the new O-ring", body="Fit the new O-ring dry.",
                warning="Lubricate the O-ring.",
                quotes=["Fit the new O-ring dry. Do not lubricate the O-ring."])
    assert r == ["warning drops 'not' from the material's warning"]


def test_warning_numbers_must_be_quoted():
    r = reasons(warning="Do not exceed 6 N-m.", quotes=[Q4])
    assert "warning says 6 N-m; no quote contains 6 N-m" in r


def test_checkpoint_value_must_be_quoted():
    q = "Check the gap under the gland plate with a 0.20 mm feeler gauge. The gauge must not enter."
    ok = reasons(label="5", glance="Check gap with 0.20 mm gauge", body="Check the gap with a 0.20 mm feeler gauge.",
                 checkpoint="0.20 mm gauge must not enter", quotes=[q])
    assert ok == []
    bad = reasons(label="5", glance="Check gap with 0.20 mm gauge", body="Check the gap with a 0.20 mm feeler gauge.",
                  checkpoint="0.25 mm gauge must not enter", quotes=[q])
    assert bad == ["checkpoint says 0.25 mm; no quote contains 0.25 mm"]


def test_part_code_changed_fails():
    r = reasons(glance="Torque M8 gland nuts to 4 N-m")
    assert r == ["glance says M8; no quote contains M8"]


def test_step_label_may_appear_in_glance():
    assert reasons(glance="Step 4: torque M6 nuts to 4 N-m") == []


@pytest.mark.parametrize("field, value, limit", [
    ("glance", "Torque the M6 gland nuts to 4 N-m in a star pattern, upper left", 60),
    ("body", "Torque the M6 gland nuts to 4 N-m in a star pattern. " * 10, 450),
    ("warning", "Isolate power and drain the pump before opening the seal housing. " * 2, 80),
    ("checkpoint", "the gap under the gland plate is checked with a feeler gauge now", 60),
])
def test_caps_after_sanitize(field, value, limit):
    quotes = [Q4, "Isolate power and drain the pump before opening the seal housing.",
              "Check the gap under the gland plate with a 0.20 mm feeler gauge."]
    r = reasons(**{field: value}, quotes=quotes)
    assert f"{field} is {len(value)} chars; the lens limit is {limit}" in r


def test_caps_measure_the_sanitized_text():
    # 60 chars as typed, but "°" sanitizes to " deg": over the cap on the lens.
    g = "Torque M6 gland nuts to 4 N-m at 20° " + "x" * 23
    assert len(g) == 60
    assert any(x.startswith("glance is 63 chars") for x in reasons(glance=g))


def test_empty_glance_fails():
    assert "glance is empty" in reasons(glance="  ")


# --- diagrams ------------------------------------------------------------------

def crop(**kw):
    return {"kind": "crop", "figure_id": "F1", "bbox": (0.1, 0.1, 0.6, 0.5),
            "alt": "Exploded view of the seal housing", "elements": [], **kw}


def test_valid_crop_passes():
    assert reasons(diagram=crop()) == []


def test_crop_of_missing_figure_fails():
    assert reasons(diagram=crop(figure_id="F9")) == ["diagram crops figure F9, which is not in the material"]


@pytest.mark.parametrize("bbox", [(0.6, 0.1, 0.1, 0.5), (0.1, 0.1, 0.1, 0.5), (-0.1, 0.0, 0.5, 0.5),
                                  (0.0, 0.0, 1.2, 0.5), None])
def test_crop_bbox_must_be_inside_and_not_degenerate(bbox):
    r = reasons(diagram=crop(bbox=bbox))
    assert len(r) == 1 and r[0].startswith("diagram crop box")


def test_schematic_with_quoted_labels_passes():
    spec = {"kind": "schematic", "alt": "Star order: upper left first",
            "elements": [{"type": "callout", "x": 60, "y": 30, "r": 14, "label": "1"},
                         {"type": "callout", "x": 500, "y": 110, "r": 14, "label": "2"},
                         {"type": "text", "x": 230, "y": 60, "label": "4 N-m"}]}
    assert reasons(diagram=spec) == []


def test_schematic_label_cap_and_element_cap():
    spec = {"kind": "schematic", "alt": "x",
            "elements": [{"type": "text", "x": 1, "y": 1, "label": "upper left nut"}]}
    assert reasons(diagram=spec) == ["diagram label 'upper left nut' is 14 chars; the limit is 12"]
    many = {"kind": "schematic", "alt": "x", "elements": [{"type": "line", "x": 0, "y": 0, "x2": 1, "y2": 1}] * 41}
    assert reasons(diagram=many) == ["diagram has 41 elements; the limit is 40"]


def test_diagram_alt_numbers_must_be_quoted():
    assert reasons(diagram=crop(alt="Seal housing, 8 bolts")) == ["diagram caption says 8; no quote contains 8"]


# --- the Protocol entry point -------------------------------------------------------

def test_verify_step_returns_v1_verify_result():
    ok = verify_step(step(), MATERIAL)
    assert ok.ok is True and ok.reason is None
    bad = verify_step(step(body="Torque to 5 N-m."), MATERIAL)
    assert bad.ok is False
    assert bad.reason == "body says 5 N-m; no quote contains 5 N-m"


def test_multiple_failures_are_all_reported():
    r = reasons(glance="Torque M8 nuts to 5 N-m", quotes=[Q4, "made up words entirely"])
    assert r[0].startswith("quote 2 is not in the material")
    assert "glance says 5 N-m; no quote contains 5 N-m" in r
    assert "glance says M8; no quote contains M8" in r


def test_accepts_attribute_objects():
    from types import SimpleNamespace as NS

    mat = NS(material_id="m", pages=[NS(**p) for p in MATERIAL["pages"]],
             figures=[NS(**f) for f in MATERIAL["figures"]])
    assert step_failures(NS(**step(diagram=NS(**crop()))), mat) == []
