"""Citation verifier test matrix. Hand-written chunks, no database, no LLM."""

import pytest

from specs_relay.pipeline.verify import check_draft, number_tokens, quote_in_text

C41 = {
    "chunk_id": "SOP-114:C:4.1",
    "doc_id": "SOP-114",
    "revision": "C",
    "section": "4.1",
    "text": "Wipe the bracket seat with isopropyl alcohol (70 %) and allow 30 s to flash off.",
}
C42 = {
    "chunk_id": "SOP-114:C:4.2",
    "doc_id": "SOP-114",
    "revision": "C",
    "section": "4.2",
    "text": "Torque all four M5 bracket screws to 4 N-m in a star pattern "
    "using a calibrated torque wrench (see SOP-131).",
}
C120 = {
    "chunk_id": "SOP-120:B:3.1",
    "doc_id": "SOP-120",
    "revision": "B",
    "section": "3.1",
    "text": "Rinse the wetted path with purified water at 60°C for 5 min.",
}
RETRIEVED = [C41, C42, C120]
Q42 = "Torque all four M5 bracket screws to 4 N-m in a star pattern"


def draft(glance, body, citations, answerable=True):
    return {
        "answerable": answerable,
        "needs_clarification": False,
        "glance": glance,
        "body": body,
        "citations": [{"chunk_id": c, "quote": q} for c, q in citations],
    }


GOOD = draft(
    "Step 4.2: torque M5 to 4 N-m",
    "Torque all four M5 bracket screws to 4 N-m in a star pattern.",
    [("SOP-114:C:4.2", Q42)],
)


# --- the required matrix ----------------------------------------------------

def test_quote_present_verbatim_passes():
    reason, cites = check_draft(GOOD, RETRIEVED)
    assert reason is None
    assert len(cites) == 1


def test_quote_with_different_whitespace_and_case_passes():
    d = draft(
        "Torque M5 to 4 N-m",
        "Torque the M5 bracket screws to 4 N-m.",
        [("SOP-114:C:4.2", "torque ALL four   M5 bracket\nscrews to 4 N-m")],
    )
    assert check_draft(d, RETRIEVED)[0] is None


def test_hallucinated_quote_fails():
    d = draft(
        "Torque M5 to 4 N-m",
        "Torque the M5 screws to 4 N-m with thread locker.",
        [("SOP-114:C:4.2", "Torque the M5 screws to 4 N-m with blue thread locker applied")],
    )
    reason, _ = check_draft(d, RETRIEVED)
    assert reason.startswith("quote_not_found")


def test_quote_from_chunk_not_retrieved_fails():
    d = draft("Torque M5 to 4 N-m", "Torque M5 to 4 N-m.", [("SOP-114:D:4.2", Q42)])
    reason, _ = check_draft(d, RETRIEVED)
    assert reason.startswith("chunk_not_retrieved")


def test_glance_value_differs_from_quote_fails():
    d = draft("Torque M5 to 5 N-m", "Torque all four M5 bracket screws.", [("SOP-114:C:4.2", Q42)])
    reason, _ = check_draft(d, RETRIEVED)
    assert reason.startswith("unsupported_number")
    assert "5" in reason


def test_number_in_no_quote_fails():
    d = draft(
        "Torque M5 to 4 N-m",
        "Torque all four M5 bracket screws to 4 N-m, then wait 30 s.",
        [("SOP-114:C:4.2", Q42)],
    )
    reason, _ = check_draft(d, RETRIEVED)
    assert reason.startswith("unsupported_number")


def test_body_converts_units_fails():
    d = draft(
        "Torque M5 to 4 N-m",
        "Torque all four M5 bracket screws to 35 in-lb in a star pattern.",
        [("SOP-114:C:4.2", Q42)],
    )
    reason, _ = check_draft(d, RETRIEVED)
    assert reason.startswith("unsupported_number")
    assert "35" in reason


# --- edges the matrix implies ----------------------------------------------

def test_fuzzy_spacing_noise_passes():
    d = draft("Torque M5 to 4 N-m", "Torque M5 to 4 N-m.",
              [("SOP-114:C:4.2", "Torque all four M5 bracket screws to 4 N-m in a star patern")])
    assert check_draft(d, RETRIEVED)[0] is None


def test_fuzzy_never_tolerates_a_changed_number():
    # One digit in a long quote is far above a 0.95 ratio; it must still fail.
    d = draft("Torque M5", "Torque the M5 screws.",
              [("SOP-114:C:4.2", "Torque all four M5 bracket screws to 5 N-m in a star pattern")])
    reason, _ = check_draft(d, RETRIEVED)
    assert reason.startswith("quote_not_found")


def test_unit_change_with_same_number_fails():
    d = draft("Torque M5 to 4 in-lb", "Torque M5.", [("SOP-114:C:4.2", Q42)])
    assert check_draft(d, RETRIEVED)[0].startswith("unsupported_number")


def test_part_code_change_fails():
    d = draft("Torque M6 to 4 N-m", "Torque the M6 screws to 4 N-m.", [("SOP-114:C:4.2", Q42)])
    reason, _ = check_draft(d, RETRIEVED)
    assert reason.startswith("unsupported_number")
    assert "m6" in reason


def test_cross_reference_code_must_be_quoted():
    d = draft("Torque M5 to 4 N-m", "Torque M5 to 4 N-m. Check wrench per SOP-132.",
              [("SOP-114:C:4.2", Q42)])
    assert check_draft(d, RETRIEVED)[0].startswith("unsupported_number")


def test_punctuation_variants_of_units_pass():
    d = draft("Torque M5 to 4 N·m", "Torque M5 to 4 N·m.",
              [("SOP-114:C:4.2", "Torque all four M5 bracket screws to 4 N·m")])
    assert check_draft(d, RETRIEVED)[0] is None


def test_degree_symbol_and_sanitized_form_agree():
    d = draft("Rinse at 60 degC for 5 min", "Rinse the wetted path with purified water at 60 degC for 5 min.",
              [("SOP-120:B:3.1", "Rinse the wetted path with purified water at 60°C for 5 min")])
    assert check_draft(d, RETRIEVED)[0] is None


def test_wrong_temperature_unit_fails():
    d = draft("Rinse at 60 degF", "Rinse at 60 degF.",
              [("SOP-120:B:3.1", "Rinse the wetted path with purified water at 60°C for 5 min")])
    assert check_draft(d, RETRIEVED)[0].startswith("unsupported_number")


def test_numbers_split_across_two_cited_quotes_pass():
    d = draft("IPA 70 %, flash 30 s, torque 4 N-m",
              "Wipe with 70 % IPA, wait 30 s, then torque all four M5 screws to 4 N-m.",
              [("SOP-114:C:4.1", "isopropyl alcohol (70 %) and allow 30 s to flash off"),
               ("SOP-114:C:4.2", Q42)])
    assert check_draft(d, RETRIEVED)[0] is None


def test_bare_count_cannot_borrow_a_value_with_a_unit():
    # Quote says 3 pulls and 4 N-m; "4 pulls" must not pass on the strength of "4 N-m".
    chunks = [{"chunk_id": "SOP-131:A:4.3", "doc_id": "SOP-131", "revision": "A", "section": "4.3",
               "text": "Set the wrench to 4 N-m and make 3 clockwise conditioning pulls."}]
    quote = "Set the wrench to 4 N-m and make 3 clockwise conditioning pulls"
    good = draft("Make 3 clockwise pulls at 4 N-m", "Make 3 clockwise pulls at 4 N-m.",
                 [("SOP-131:A:4.3", quote)])
    assert check_draft(good, chunks)[0] is None
    bad = dict(good, glance="Make 4 clockwise pulls")
    assert check_draft(bad, chunks)[0].startswith("unsupported_number")


def test_dropping_the_unit_from_a_value_fails():
    d = draft("Torque M5 to 4", "Torque the M5 screws.", [("SOP-114:C:4.2", Q42)])
    assert check_draft(d, RETRIEVED)[0].startswith("unsupported_number")


def test_answerable_without_citations_fails():
    d = draft("Torque M5 to 4 N-m", "Torque M5 to 4 N-m.", [])
    assert check_draft(d, RETRIEVED)[0] == "no_citations"


def test_not_answerable_never_passes():
    d = draft("", "", [], answerable=False)
    assert check_draft(d, RETRIEVED)[0] == "not_answerable"


def test_needs_clarification_never_passes():
    d = dict(GOOD, needs_clarification=True)
    assert check_draft(d, RETRIEVED)[0] == "not_answerable"


def test_empty_quote_fails():
    d = draft("Torque M5", "Torque M5.", [("SOP-114:C:4.2", "  ")])
    assert check_draft(d, RETRIEVED)[0].startswith("quote_not_found")


def test_short_quote_must_be_exact():
    d = draft("Torque M5", "Torque M5.", [("SOP-114:C:4.2", "M6 bracket")])
    assert check_draft(d, RETRIEVED)[0].startswith("quote_not_found")


def test_glance_over_cap_fails():
    d = dict(GOOD, glance="Torque all four M5 bracket screws to 4 N-m in a star pattern now")
    assert check_draft(d, RETRIEVED)[0] == "glance_too_long"


def test_body_over_cap_fails():
    d = dict(GOOD, body="Torque all four M5 bracket screws to 4 N-m. " * 12)
    assert check_draft(d, RETRIEVED)[0] == "body_too_long"


def test_citations_carry_doc_revision_section():
    _, cites = check_draft(GOOD, RETRIEVED)
    assert cites == [{
        "chunk_id": "SOP-114:C:4.2",
        "doc_id": "SOP-114",
        "revision": "C",
        "section": "4.2",
        "quote": Q42,
    }]


def test_accepts_attribute_objects():
    from types import SimpleNamespace as NS

    chunks = [NS(**c) for c in RETRIEVED]
    d = NS(**{**GOOD, "citations": [NS(**c) for c in GOOD["citations"]]})
    assert check_draft(d, chunks)[0] is None


# --- tokenizer --------------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("torque M5 to 4 N-m", {"code:m5", "4|nm"}),
        ("4 N·m", {"4|nm"}),
        ("35 in-lb", {"35|inlb"}),
        ("70 % IPA for 30 s", {"70|%", "30|s"}),
        ("70% for 30 sec", {"70|%", "30|s"}),
        ("60°C", {"60|degc"}),
        ("4 screws in 2 rows", {"4|", "2|"}),
        ("4 +/- 0.2 N-m", {"4|", "0.2|nm"}),
        ("see SOP-131 for the HX-2", {"code:sop-131", "code:hx-2"}),
        ("20-25 s", {"20|", "25|s"}),
        ("1,500 rpm", {"1500|rpm"}),
        ("torque to 4 in a star pattern", {"4|"}),
    ],
)
def test_number_tokens(text, expected):
    assert number_tokens(text) == expected


def test_quote_in_text_basic():
    assert quote_in_text("Bracket Screws", C42["text"])
    assert not quote_in_text("bracket bolts", C42["text"])
