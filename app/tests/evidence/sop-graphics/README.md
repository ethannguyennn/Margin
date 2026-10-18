# Accompanying SOP graphics: current-main port

Official Even Hub simulator 0.9.5, SDK 0.0.16, Windows WebView2, VITE_MOCK=1.
Native captures show a coffee steam-wand reference beside both the glance and full
instruction text. The phone capture shows the same cropped figure and synthetic caption.
The existing two-tile diagram viewer also passed. Simulator exports store intensity in
alpha; previews composite those original captures on black using the existing QA method.

`simulator-results.json`: 28 screen assertions, reference image transport, existing M1/M2
flows, ordered progress, native exit, cold-start restore and zero console errors.
`live-gemini-selections.json`: separate approved real Gemini calls over the five synthetic
coffee SOP excerpts, with all five image selections citation-verified.

Final verification: relay 668 passed / 12 skipped; app 552 passed / 12 skipped; build and
pack pass (Specs package 4,911,875 bytes). Skips are opt-in live/database tests; the new live
image-selection test was run separately and passed. Physical glasses, BLE throughput and
live audio were not tested. The mock phone capture reports Offline because no relay server
was configured; the image and answer arrived through the actual simulator lens link.

Regenerate with `npm run dev:mock:v2` and `npm run test:simulator` in app. Original full logs
and captures remain in ignored `app/test-artifacts/v2/`. The source artwork is in
`app/src/assets/sops/`, generated using built-in imagegen from the prompt set in
`corpus/illustration-prompts.json`. No generated image is a verified real equipment photo.
