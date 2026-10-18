# Part 4 handoff: conversion, diagrams, command intents

Branch `part-4-conversion-diagrams`. Final tested code commit: **`58fd795`** (this file
and the four real tiles are added on top of it; no code changes after it).

Nothing here has run against `v2-scaffold-relay`: Part 3 had not pushed it. Every module
returns plain dicts shaped like the BUILD-PLAN-V2 section 5 models and wraps them in
`schemas.*` lazily, so the Protocol methods work as soon as the scaffold is merged.

## What is done

| Piece | File | Status |
|---|---|---|
| `parse_command` + `command` intent | `pipeline/intent.py` | Done. Every section 3 phrase parses; must-not-match phrases stay questions |
| Draft verifier | `convert/verify_step.py` | Done. Deterministic, readable reasons |
| Extraction | `convert/extract.py` | Done. Markdown, DOCX, PDF text layer, Gemini OCR (photo / scanned page), Gemini figure boxes |
| Structuring | `convert/structure.py` | Done. One structured call per page chunk, verify, one retry, never drops a step. `GeminiConverter` implements `Converter` |
| Renderer | `diagrams/render.py` | Done. Crop + schematic, 2 PNG tiles, lens-exact preview, page images |
| Synthetic materials | `corpus/materials/` | Done. 4 materials + `build_materials.py` |
| Conversion eval | `eval/conversion/` | Done. Real Gemini results committed |
| v1 sanitizer mismatch (TODO 4) | `pipeline/sanitize.py` | Fixed. 8/8 app fixtures agree |
| v1 lexical leg (TODO 4) | Part 5's `db.py` | Closed by Part 5: they adopted the OR'ed query from `PgStore` |

## Commands

Tests (relay venv with `Pillow pypdf pypdfium2 python-docx` installed, see Open requests):

```
cd relay
pytest tests/test_intent.py tests/test_verify_step.py tests/test_render.py \
       tests/test_extract.py tests/test_structure.py tests/test_sanitize.py tests/test_verify.py
pytest                                          # whole relay suite
SPECS_LIVE_GEMINI=1 pytest tests/test_live_gemini.py   # live v1 Gemini checks, opt-in
SPECS_UPDATE_GOLDEN=1 pytest tests/test_render.py      # regenerate goldens, deliberately
```

Conversion eval (keys from `.env` via Part 3's config; the model is never defaulted):

```
python eval/conversion/run_conversion_eval.py --model gemini-3.8-flash          # live, all four
python eval/conversion/run_conversion_eval.py --model gemini-3.8-flash --only SOP-150 --force-hallucination
python eval/conversion/run_conversion_eval.py --from-saved eval/conversion/results/2026-10-17-gemini-3.8-flash \
       --model-label gemini-3.8-flash                                           # re-score saved real output, no API
```

Exit 1 = a passing step contains a value the material does not (the gate). `--strict` also
exits 2 when steps, values or expected diagrams are missing. Rebuild the materials with
`python corpus/materials/build_materials.py`.

## Test results (2026-10-17, commit `58fd795`)

| Suite | Result |
|---|---|
| test_intent | 93 passed |
| test_verify_step | 36 passed |
| test_render | 17 passed (2 golden images, exact pixel match) |
| test_extract | 21 passed |
| test_structure | 15 passed |
| test_sanitize | 37 passed (includes the app's own fixture file) |
| test_verify (v1) | 40 passed |
| Whole relay suite | 489 passed, 8 skipped, 1 xfailed |

Skips: 3 live Gemini tests (opt-in), 5 Postgres tests (need `SPECS_TEST_PG_DSN`). The xfail is
`test_ask_trust` "say that again", which becomes `intent: command` and needs the v2 `Intent`
literal from `v2-scaffold-relay`; it is strict, so it flips red when the scaffold lands and
must then be un-marked. Live Gemini tests, run once opted in: 3 passed (transcribe the PCM
fixture, 768-dim `gemini-embedding-2`, verified answer and refusal on `gemini-3.5-flash-lite`).

## Conversion eval: real Gemini output

Model **`gemini-3.8-flash`**, verified 2026-10-17 in Google's model list
(ai.google.dev/gemini-api/docs/models: stable, "most intelligent Flash") and in
`models.list()` for our key. Bounding boxes use Gemini's documented
`box_2d = [ymin, xmin, ymax, xmax]` in 0-1000, converted to the contract's 0..1 `(x0, y0, x1, y1)`.

| Material | Path | Steps | Values kept | Failing | Expected diagram | Fabricated |
|---|---|---|---|---|---|---|
| SOP-150 PDF | text layer + figure boxes | 6/6 | 9/9 | 0 | crop on 3.4 | 0 |
| SOP-151 DOCX | paragraphs, table, embedded image | 7/7 | 9/9 | 0 | crop on 4 | 0 |
| SOP-152 photo | OCR + figure boxes | 5/5 | 7/7 | 0 | crop on 1 | 0 |
| SOP-153 markdown | schematic | 4/4 | 5/5 | 0 | schematic on 3 | 0 |

No converted units anywhere. Evidence in `eval/conversion/results/2026-10-17-gemini-3.8-flash/`:
`material_text.json` and `draft.json` per material (the real model output), lens-exact
previews per diagram step, and `report.json`. Notable output: the photo was transcribed
verbatim (including `45°` and `0.5 bar`), each valve got its own crop, and "Never open V2
before V4 is set" was attached to step 5 only.

How the numbers were produced, honestly: SOP-153 converted live in one run; SOP-150/151/152
converted live in a second run, which then hit the free-tier daily cap on SOP-153 (see
Limitations). Both runs saved their real outputs; the table is `--from-saved` re-scoring of
those four real drafts with the final verifier and renderer. One structuring call took 77 s.

**Forced hallucination** (4 N-m -> 5 N-m in glance/body, never in quotes):

- On the real SOP-150 draft: step 3.4 fails with
  `glance says 5 N-m; no quote contains 5 N-m; body says 5 N-m; no quote contains 5 N-m`.
  Gate stays 0 (the fabricated value is only in a failing step).
- Live on `gemini-3.7-flash` (different model, its own quota): figure pass + structuring + one
  retry with the reasons; the wrapper hallucinates the retry too, so 3.4 is returned failing,
  not dropped. Report in `results/2026-10-17-gemini-3.7-flash-forced-hallucination/`.

## v1 eval (zero unverified answers)

Real-mode relay on this laptop against the seeded shared database (59 chunks / 35 steps),
`gemini-3.5-flash-lite` + `gemini-embedding-2`, gate thresholds unset (stricter: refusals rely
on generator + verifier). Requests paced 8 s apart to stay under the free tier.

**0 unverified answers**; citation-verification pass 100 %; answered-correct 93.8 % (15/16);
not_found precision 95.0 %, recall 95.0 %; near-miss 10/10, off-domain 6/6, ambiguous 3/4.
Failures: `a16` unexpected outcome, `c03` missing `needs_clarification`. The 8 s median latency
is the pacing, not the relay. Report: `eval/conversion/results/2026-10-17-v1-eval-live-relay.json`.
An earlier unpaced run hit HTTP 429s on 23 questions; the relay turned every one into
`llm_timeout`, never an answer.

## Diagram byte format and sizes

Part 2 proved in evenhub-simulator 0.9.5 that `updateImageRawData` renders **8-bit greyscale
PNG** with every pixel already at a lens level (`level * 17`). `render.TILE_FORMAT = "png"`;
packed 4-bit (high nibble = left pixel) is implemented and tested as the proven fallback, a
one-line switch. Canvas 576 x 144 -> always two 288 x 144 tiles (slot 0 left, slot 1 right).

- Crop: autocontrast, invert when the mean is above 50 %, fit keeping aspect, integer
  Floyd-Steinberg to 16 levels (deterministic on every Pillow).
- Schematic: level-15 strokes 2 px, Atkinson Hyperlegible Bold (SIL OFL, bundled in
  `diagrams/fonts/`) at 21 px = 14 px cap height, numbered callouts.
- Real tile sizes: **652-2,698 bytes** per tile across all 14 real diagrams, under the 8 KB budget.
- `preview_png(tiles)` = 576 x 144 RGB, level 15 = G2 green `#3CFA44`. Served by Part 3 at
  `/v1/diagrams/{id}/preview.png` for Part 5's portal.
- For Part 2's BLE timing: real tiles in `results/2026-10-17-gemini-3.8-flash/tiles/`
  (SOP-150 3.4 crop: 1,046 + 1,111 bytes; SOP-153 3 schematic: 766 + 777 bytes). The file bytes
  are exactly what goes in `DiagramImage.tiles[].image` (base64).

## Integration notes for Part 3

- `GeminiConverter.from_settings(settings, client=None)` reads `settings.gemini_model_convert`
  and raises if empty. `extract()` keeps the material's bytes by `material_id` (last 8) so
  `convert()` can show the model the figures to crop; call both on the same instance.
- `verify_step(step, text) -> VerifyResult` with `citations=[]` and `reason` = every failure
  joined by `"; "`. `convert.verify_step.step_failures()` returns them as a list for the portal.
- `render.render(spec, page_image)`, `preview_png(tiles)`, `page_image(data, mime, page)`.
  DOCX has no pages: figure k has `page = k`, meaning the k-th embedded image; `page_image`
  uses the same rule.
- Typed errors: `ExtractionError.code = "bad_request"` (unsupported/corrupt file),
  `StructureError.code = "llm_timeout"`. A page that times out never raises: it becomes
  `[page N failed to read]` and any step quoting it fails.
- `classify_intent` returns `"command"` before every other rule; `parse_command(t)` gives the
  `Command`. "repeat" and "say that again" are now commands: outside a task the lens or `/v1/ask`
  should treat command `repeat` as v1 `repeat`. "repeat the warning about power" stays a
  question (answered from the warning chunk). "what was that" keeps v1 `repeat`.
- Windows dev only: uvicorn's Proactor loop breaks psycopg async (`db: down`). Production
  (Linux Docker) is unaffected. Locally I ran
  `asyncio.run(uvicorn.Server(config).serve(), loop_factory=asyncio.SelectorEventLoop)`.

## Limitations

- **Free-tier Gemini key.** `gemini-3.8-flash` allows 20 requests/day per project and
  `gemini-3.5-flash-lite` 15/min. One full conversion of the four materials is about 8-10
  calls; two runs exhaust the day. A paid key is needed before the M3 demo.
- **Structuring is slow**: 60-80 s per call on `gemini-3.8-flash` (it thinks). Fine as a
  background job; the portal must show "converting".
- `gemini-3.7-flash` took more than 60 s on a figure pass; the extraction timeout is now 90 s.
  On a timeout the text layer is kept but that page has no figures, so no crop.
- Crops from the materials keep the figure's own small labels (about 9 px on the lens for
  SOP-150). Legibility on real glasses is unverified (no hardware).
- Not run: `v2-scaffold-relay` integration, the M3 portal flow, Postgres integration tests
  against Tiger (they need `SPECS_TEST_PG_DSN`), BLE tile timing, the photo crop on a real lens.

## Open requests

- **Part 3:** add to `pyproject.toml`: `Pillow`, `pypdf`, `pypdfium2`, `python-docx`.
  Add `GEMINI_MODEL_CONVERT` to `config.py` / `.env.example` (value: `gemini-3.8-flash`).
  Add `make eval-conversion` -> `$(PY) eval/conversion/run_conversion_eval.py $(ARGS)`.
  Push `v2-scaffold-relay`; I will merge it and remove the lazy-schema shims' dict paths.
- **Part 1:** add the ohm sign U+2126 -> `" ohm"` to `glyphs.ts`. The relay now also maps
  Greek omega U+03A9 and drops control characters, exactly as the app does. Copy
  `relay/tests/fixtures/glyph_cases.json` (32 cases) into the app suite.
- **Part 2:** time the four real tiles in `results/.../tiles/` over BLE.
- **Part 5:** the portal can show `step_failures()` reasons directly; they are written for
  supervisors. Preview PNGs are 576 x 144 RGB.
