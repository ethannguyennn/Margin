# Part 4 v2 — Material Conversion, Diagrams & Command Intents

**Branch:** `part-4-conversion-diagrams`
**Read first:** `BUILD-PLAN-V2.md` (§4 diagrams, §5 `MaterialText`, `DraftStep`, `DiagramSpec`, Protocols).
**Owns:** turning an employer's instructional material into a verified,
step-by-step procedure with diagrams, and recognising voice commands. v1's
thesis (never show an unquoted number) now applies to authoring: a converted
step that cannot be traced to the source material is a failed step, not a
best guess.

**Milestones:** M2 (command intents, renderer producing lens tiles), M3
(real conversion of the synthetic materials), M5 (conversion eval numbers).

---

## 1. Files you own

```
relay/src/margin_relay/convert/__init__.py
relay/src/margin_relay/convert/extract.py     # bytes -> MaterialText (pages verbatim + figures with bboxes)
relay/src/margin_relay/convert/structure.py   # MaterialText -> ProcedureDraft (Gemini, structured output)
relay/src/margin_relay/convert/verify_step.py # deterministic draft verifier, reuses pipeline/verify.py
relay/src/margin_relay/diagrams/render.py     # DiagramSpec -> lens tiles + preview PNG (Pillow)
relay/src/margin_relay/pipeline/intent.py     # + 'command', parse_command()
relay/src/margin_relay/pipeline/{transcribe,retrieve,generate,verify,sanitize}.py   # v1, maintenance only
corpus/materials/                              # synthetic demo inputs (see §7)
eval/conversion/                               # expected outputs + run_conversion_eval.py
relay/tests/test_extract.py, test_structure.py, test_verify_step.py, test_render.py, test_intent.py
```

## 2. Files you must NOT touch

`main.py`, `config.py`, `schemas.py`, `routes/`, `jobs.py`, `auth.py`,
`pipeline/__init__.py`, `pipeline/mock.py`, `Makefile`, `.env.example`
(Part 3); `db.py`, `db/`, `walkthrough.py`, `notify/`, `portal/`,
`corpus/*.md`, `eval/qa.jsonl` (Part 5); all of `app/`, `ios/`; and **`main`**.

New deps or env vars: post them to Part 3. Expected: `Pillow` (render/crop),
`pypdf` (PDF text layer), `pypdfium2` (PDF page -> image for crops; Apache-2.0,
do **not** use PyMuPDF, it is AGPL), `python-docx` (DOCX text + embedded
images). That is the whole list; justify anything beyond it.

Depend on `v2-scaffold-relay` (`git fetch --tags && git merge v2-scaffold-relay`).

---

## 3. Command intents (`intent.py`) — do first, it is an hour

`parse_command(transcript) -> Command | None` per BUILD-PLAN-V2 §3: the
**whole utterance** (after stripping filler: ok, okay, um, uh, please, margin,
hey) must be the command. `classify_intent` returns `'command'` when
`parse_command` matches, before every other rule.

Tests: every phrase in the §3 table; and must-not-match: "what's the next step's
torque", "go back to the torque value", "show me the M5 spec", "is this
step done right", "repeat the warning about power" (that last one stays
v1 `question`/`repeat` behaviour; decide with Part 1 and write it down).

## 4. Extraction (`extract.py`)

Goal: a verbatim text of what the material says, per page, plus figures with
locations. This is what the supervisor reviews and what every quote is
checked against, so it must be faithful, not pretty.

| Input | Text | Figures |
|---|---|---|
| PDF with text layer | `pypdf` per page | Gemini: one call per page image (`pypdfium2` at 150 dpi) asking for figure bboxes + captions only |
| Scanned PDF / PNG / JPEG | Gemini: verbatim transcription to markdown, one call per page | same call returns figure bboxes |
| DOCX | `python-docx` paragraphs + tables -> markdown | embedded images become figures (bbox = whole image) |
| Markdown / text | as is | none |

Rules for the Gemini transcription prompt: verbatim, keep every number, unit,
symbol and warning exactly; no summarising, no reordering, no fixing typos;
mark unreadable text as `[illegible]`. Structured output (`pages[]`,
`figures[]`), low temperature, `GEMINI_MODEL_CONVERT`. Bboxes are normalised
0..1. Hard timeout per call; a page that fails is `[page N failed to read]`,
which makes any step quoting it fail verification. Never guess.

## 5. Structuring (`structure.py`)

One structured-output call over the whole `MaterialText`: returns the
`ProcedureDraft` steps. Prompt rules (keep every one):

```
You convert employer instructions into a step-by-step procedure for smart glasses.
Use ONLY the provided MATERIAL. Never add steps, values, tools or warnings that are not in it.
1. One physical action per step, in the order the material gives. Do not merge or reorder.
2. glance: <= 60 chars, imperative, include the key value + unit. body: <= 450 chars, plain sentences.
3. warning: the material's own warning text for this step, shortened only by deletion, <= 80 chars. Else null.
4. checkpoint: a measurable acceptance check from the material, <= 60 chars. Else null.
5. quotes: verbatim spans copied from MATERIAL that support every claim in glance, body, warning, checkpoint.
6. Preserve numbers, units and warnings exactly. Never convert units.
7. diagram: if a FIGURE shows this step, {kind:'crop', figure_id, bbox of the relevant region}.
   Else if the material describes a spatial layout for this step (positions, order, orientation),
   {kind:'schematic', elements:[...], alt} using only labels present in the quotes. Else null.
Return JSON matching the schema.
```

Long materials: chunk by page ranges with overlap, then concatenate; a step
must not straddle a seam (prompt the second call with the last step of the first).

## 6. Draft verifier (`verify_step.py`) — deterministic, no LLM

A step passes only if **all** hold (reuse v1 `verify.py` normalisation and
number+unit tokeniser; do not fork it):

1. Every quote appears in `MaterialText` (normalised, fuzzy >= 0.95, as v1).
2. Every number+unit token in `glance`, `body`, `warning`, `checkpoint` and
   every schematic `label` appears in at least one of the step's quotes.
3. A `warning` is present in a quote (it is the material's own warning).
4. Caps hold after `sanitize()`.
5. A crop's `figure_id` exists; its bbox is inside 0..1 and not degenerate.

Failure reasons are human-readable ("body says 5 N-m; no quote contains 5 N-m")
because the supervisor reads them in the portal. Structuring gets one retry
with the failure reasons for failing steps only; still failing -> the step is
returned failing, never silently dropped (a dropped safety step is worse than a
red one in the review screen).

Test matrix (write first): verbatim pass; whitespace/case pass; hallucinated
quote fail; torque changed in body fail; unit converted fail; warning not in
source fail; schematic label "6 Nm" absent from quotes fail; `[illegible]`
region quoted fail.

## 7. Diagram renderer (`diagrams/render.py`)

`render(spec, page_image) -> list[bytes]` returns 1-2 tiles in **the byte
format Part 2 proves on day one** (BUILD-PLAN-V2 §4); `preview_png(tiles)`
returns a 576x144 PNG that looks exactly like the lens (green on black) for the
portal.

- **crop:** crop the page image to `bbox`, greyscale, autocontrast, **invert
  when the background is light** (mean > 50 %), fit into 576x144 keeping
  aspect, Floyd-Steinberg to 16 levels, split into two 288x144 tiles (or one
  if it fits in 288).
- **schematic:** draw `elements` with Pillow on a black 576x144 canvas,
  level-15 strokes 2 px, bundled bitmap-friendly font (ship one OFL font file
  in the repo), labels >= 14 px cap height, callouts as numbered circles.
- Pure functions, golden-image tests: render the committed specs and compare
  against committed PNGs (exact match; regenerate deliberately).
- Size budget: each tile, in lens format, after the SDK's LZ4, should be
  < 8 KB for line art. Log it; Part 2 measures the BLE time.

## 8. Synthetic demo materials (`corpus/materials/`)

Make these yourself, synthetic, on the same fictional Halcyon HX-2 pump:

| File | Exercises |
|---|---|
| `SOP-150-pump-seal-swap.pdf` | text-layer PDF, 6 steps, one exploded-view figure, one warning box |
| `SOP-151-filter-change.docx` | DOCX with a table of torque values and an embedded image |
| `SOP-152-valve-lineup-photo.jpg` | phone photo of a printed page (slight skew, shadow): OCR path + crop |
| `SOP-153-quick-start.md` | plain text, a star-pattern description with no figure: schematic path |

Each gets an expected file in `eval/conversion/` listing step count,
`must_contain` values per step and which steps must have a diagram.

## 9. Conversion eval (`eval/conversion/run_conversion_eval.py`)

Runs each material through the real `extract -> convert -> verify_step ->
render` (no HTTP needed) and prints: steps found vs expected, values preserved
(every `must_contain`), steps failing verification, diagrams produced,
and — the gate — **fabrication count: values in any step that are not in the
material**. Exit non-zero if any *passing* step contains a fabricated value.
That is the regression that must never ship.

## 10. Build order

1. `parse_command` + tests (hour one). Tell Part 3.
2. `verify_step` test matrix + implementation over hand-written `MaterialText`.
3. `render.py` with golden images; announce preview PNGs to Part 5.
4. Synthetic materials + expected files.
5. `extract.py` (text/markdown/docx first, then PDF text layer, then Gemini OCR).
6. `structure.py`, then the eval, then tune prompts against it.
7. v1 maintenance from `TODO.md` §4 (sanitizer disagreement with the app, lexical
   leg AND vs OR, with Part 5).

## 11. Acceptance

- [ ] Command phrases parse; every must-not-match stays a question.
- [ ] `make eval-conversion` (ask Part 3 for the target): all four materials,
      0 fabricated values in passing steps, every expected diagram produced.
- [ ] A forced hallucination (monkeypatched structurer changes 4 N-m to 5 N-m) fails verification with a readable reason.
- [ ] Golden-image tests pass; the photo material's crop is inverted and legible in the preview.
- [ ] No unit conversions anywhere (grep the eval output for converted units).
- [ ] v1 `make eval` still shows zero unverified answers.
- [ ] `make test` green.

## 12. House rules

Every v1 rule (BUILD-PLAN-V2 §8). Synthetic material only. All keys via Part 3's
config; never log a prompt that contains material text at INFO or above.
Refusing to convert a step is a feature. Do **not** add `Co-Authored-By: Claude`
to commits.
