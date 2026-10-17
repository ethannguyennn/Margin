# Actual simulator evidence

Captured from official Even Hub simulator 0.9.5 on Windows, SDK 0.0.16,
`VITE_MOCK=1`, on 2026-10-17. These are synthetic UI fixtures, not a tested
relay/audio/Sentry integration. Only the official `/api/input` gesture endpoint
was used to drive screens; no state injection or browser click controls.

`simulator-results.json` records the 29 assertions. The API accepted root
shutdown with mode 1 and cleared its active page; no SYSTEM_EXIT_EVENT was
observed. Confirmation behavior on physical glasses needs device testing.

PNG previews are the native 576x288 captures composited on black to display
the simulator's alpha-only glyph intensity. Original captures and full console
logs are generated into ignored `test-artifacts/` by the smoke test; regenerate
previews with `tests/render-simulator-captures.ps1`.

The separate unit suites test cold-start restoration using serialized native
storage values; simulator process restarts are not claimed as storage evidence.
