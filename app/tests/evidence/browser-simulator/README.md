# Browser glasses simulator evidence

Captured on Windows on 2026-10-18. These are browser previews, not captures from
physical G2 glasses or the official desktop simulator.

- `worker-dark.png`: worker Lens tab, existing dark theme, mock walkthrough step.
- `portal-light-diagram.png`: admin Simulator page, existing light theme, two
  approved diagram tiles loaded through the local mock relay.

The worker used `VITE_MOCK=1`; the portal used the actual FastAPI app with
`MOCK_MODE=1` and the public mock workspace code `DEMO`. No Gemini requests,
cloud writes or physical-glasses results are claimed.

Manually checked: portal login -> Simulator -> typed walkthrough -> swipe to
another step -> details -> typed "show diagram" -> both tiles; worker typed
walkthrough -> live STEP preview; theme and typography preserved. Shared unit
tests also cover answer/details, step context, unverified refusal, cancellation,
root exit/reset, image cleanup, warnings, and connected/disconnected mirroring.

Validation: `mingw32-make test` passed: 891 relay tests (13 skipped), 625 app tests
(12 skipped), 10 portal tests. Worker build/typecheck and portal build/typecheck
passed. The test settings helper now isolates `GIT_SHA` so Make's exported
deployment version does not break the mock-health fixture.

Reproduce locally in separate terminals (Windows uses `mingw32-make`):

```powershell
# Relay: only synthetic fixtures, no provider/database access.
$env:MOCK_MODE = '1'
mingw32-make diag-relay RELAY=http://127.0.0.1:8080

# Portal: http://127.0.0.1:5178/portal/#simulator ; workspace code DEMO
npm --prefix portal run dev

# Worker: http://localhost:5174/#/lens
npm --prefix app run dev:mock
```

The portal's production simulator requires the accompanying relay routes to be
deployed. Production asks use the signed-in workspace's real pipeline. The portal
simulator is a separate session; it does not mirror remote workers' devices.
Inside the Even app, the worker Lens preview instead subscribes to the connected
lens's structured text and image frames. Hardware mirroring is unit-tested with
bridge snapshots; it has not been tested on physical glasses for this change.

Both previews share hardware container geometry and the real LensController /
renderScreen implementation. Browser font metrics and display glow are approximate.
