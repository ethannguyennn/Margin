# SOP reference graphics diagnostic

The current coffee corpus was seeded from text-only Markdown. The newer upload/conversion
pipeline can render supervisor-approved diagrams, but seeded steps have no diagram records,
and question generation had no image catalog or selection field. Phone and lens answer views
therefore displayed only text even when Gemini answered correctly.

The port adds five generated reference images for SOP-201, 202, 210, 220 and 230, with ten
equipment views. `corpus/illustrations.json` pins every view to an exact revision and source
anchor. Gemini sees only views supported by retrieved chunks; its `graphic_id` must match a
verified citation. Walkthroughs choose their matching view deterministically. Unknown IDs,
URLs, changed source text and uncited selections are rejected. Text-only steps stay text-only.

Phone answers, walkthroughs, SOP lists and the live lens mirror display the same reference.
The lens adds a 288 x 144 native Gray8 image beside paginated text. It clears stale references
before changing instructions, and retains the existing two-tile DIAGRAM viewer and approvals.
Steps with long warnings/checkpoints keep their full-width step text; their paginated details
show the accompanying image. Generated art depicts fictional demo equipment, not site-specific
part identification. Replace it with approved site photographs for actual work.

Generation previously timed out internally at six seconds, irrespective of the configured
seven-second route guard; the client stopped at eight seconds. Provider and route now share
a configurable twenty-second default, with fifty seconds on the client for two attempts plus
transcription/retrieval. No new model or API dependency is introduced.

New coffee art: `app/src/assets/sops/`. Prompts: `corpus/illustration-prompts.json` (built-in
imagegen; blind basket edited to a solid bottom). Original HX-2 images and their catalog are
retained beside that retired corpus in `relay/tests/fixtures/hx2-corpus/`.

Run `npm test` and `npm run pack` in app, and `python -m pytest -q` in relay.
Live check: `SPECS_LIVE_GEMINI=1 python -m pytest -s tests/test_live_gemini.py -k reference_graphics`
with the configured Gemini key/model. No database migration or data replacement is needed.
Deploy the updated relay and install the rebuilt Specs package to use the feature.


Verified on 2026-10-18: relay 668 passed / 12 skipped; app 552 passed / 12 skipped;
five live Gemini selections verified; native simulator 28 assertions and zero console
errors; production build and package passed. Evidence: `app/tests/evidence/sop-graphics/`.
Physical glasses and live audio were not available for this check.
