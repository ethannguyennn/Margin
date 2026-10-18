# Part 1 v2 — lens handoff

## Tested revision and dependency tag

Final tested implementation: `82fc3339e0f48107788416878d6f53d8faf07ecd`
on `part-1-lens-hands-free-ui`. The following evidence/documentation commit
does not change runtime code.

`v2-scaffold-app` is `5d6d5bd`. `app/src/types.ts` was extracted verbatim
from BUILD-PLAN-V2 section 5 and pushed before implementation. It has not been
changed to accommodate downstream errors. The tag was announced in the current
chat; no separate team channel was provided.

The original main checkout, live relay, private configuration and v1 lens
checkout were preserved. This checkout is `lens-v2-worktree`.

## Commands

Node 22.12+; tested with Node 24. Windows PowerShell commands from `app/`:

```powershell
npm.cmd ci
npm.cmd run dev:mock:v2
```

In another terminal, also from `app/`:

```powershell
npm.cmd run simulate:v2
```

This uses port **5176**, simulator automation **9899**, and local WebView2
debugging **9224**, leaving the earlier live Vite server on 5174 intact.
The simulator launcher defaults to the M1 fixture scenario. For a manual M2
run, open `http://localhost:5176/?scenario=m2` in its Browser window. A mock
pair code is claimed after five seconds, then the assignment arrives.

```powershell
npm.cmd test
npm.cmd run build
npm.cmd run pack
# Keep dev:mock:v2 running. Close manual/other simulator windows first.
npm.cmd run test:simulator
```

`test:simulator` starts and closes its own native simulator instances for M1
and M2. It clicks the actual dev Nod/Shake DOM buttons over the simulator
WebView's CDP connection; it does not inject controller state. Windows
WebView2 profiles must be isolated, and another running simulator can claim
the app-view profile before the test's debug port is set. The normal
`simulate` and v1 port commands remain available.

The production pack is `app/specs.ehpk` (ignored), SDK 0.0.16, minimum Even
App 2.2.10. Dev controls require a development build and `VITE_MOCK=1` or
`?dev=1`; they are not available in the packaged production app.

Repository milestone check, exactly as run from the v2 checkout root:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'relay/src'
mingw32-make test 'PY=C:/Users/miles/OneDrive/Desktop/LAHacks/Specs/.venv/Scripts/python.exe'
```

This interpreter already has `relay[dev]` installed. For a fresh clone, use
its own Python environment with those dependencies. The PYTHONPATH above
ensures the tests import this checkout's relay, not the earlier editable install.

## Actual results

- App: **418 passed, 6 skipped**; nine test files passed and the live-relay
  file was skipped. The skipped tests require an explicitly configured relay.
- Build and pack: **passed**. No dependency or second lockfile was introduced.
- Native simulator 0.9.5: **25 screen assertions passed**. M1 uses one dev
  Nod after setup, automatic endpointing, and the real 20-second dim timer.
  No tap is used in that measured flow. Setup acknowledges first-run privacy.
- M2: assigned mock task -> TASK_READY -> Nod -> STEP 1 -> two mock `next`
  utterances -> STEP 3 -> mock `show diagram` -> two rendered tiles -> Shake
  -> STEP 3. No step-navigation request was needed.
- Progress order: `task_started`, `step_started(1)`, `step_completed(1)`,
  `step_started(2)`, `step_completed(2)`, `step_started(3)`. Timestamps are
  strictly increasing, even when the clock returns the same millisecond.
- Rebuild counter: **M1=0; M2=2**, exactly TEXT->DIAGRAM and DIAGRAM->TEXT.
  Unit tests also assert caption/image-only changes do not rebuild and
  each tile is awaited before the next.
- Answer, NOT_FOUND and ERROR each return to STEP 3. Empty capture calls
  no `ask`, and preserves the original screen, detail page and task index.
- Actual native-storage restart: pause at STEP 3, root native shutdown,
  reload the WebView, re-pair the fixture, and restore STEP 3. Unit tests
  additionally cover strict 12-hour assignment and 30-minute ad-hoc expiry.
- Native root double tap is accepted and clears the page. As in v1, the
  simulator does not supply a SYSTEM_EXIT_EVENT confirmation in this run.
- No simulator console errors. Captures wait for SDK display updates to finish
  and allow 160 ms for frame presentation, rather than sampling the earlier
  state-transition log.
- Relay regression suite: **343 passed, 8 skipped**. One dependency
  deprecation warning from Starlette/httpx was reported.
- **Whole `make test` is blocked at `test-ios`**: the companion's two
  exhaustive `Record<Outcome,...>` maps in `ios/src/components/Pills.tsx`
  lack the new `command` member. No unowned companion file was edited.

Evidence: `app/tests/evidence/v2/results.json` and the adjacent PNGs. Full
console logs and original RGBA captures are regenerated into ignored
`app/test-artifacts/v2/`. The previews composite the simulator's alpha-only
glyph/image intensity on black; original captures are retained unchanged.

## Runtime and compatibility notes

Every screen/gesture pair, including no-ops, is tested. The v1 suites are
retained; assertions were migrated only where the v2 specification explicitly
changes privacy->calibration, WALKTHROUGH->STEP, step details tapping, task
completion, or protected-screen timeout behavior.

The legacy WALKTHROUGH renderer/type remains as a compatibility alias, while
new walkthrough responses and restored sessions enter STEP. The storage key
continues reading v1 data. Task state persists no token, raw audio, response,
answer-return snapshot, or IMU sample. Device credentials remain Part 2's job.

Paused tasks keep their place. Deferred TASK_READY tasks emit their start
events once when resumed. Completed tasks cannot emit completion twice.
An ad-hoc walkthrough answer cannot replace an active assigned task.

Pairing occurs on boot. Assignment polling is every 10 seconds only in
foreground IDLE without an active task. Current and next step diagrams are
prefetched on step changes, with an eight-diagram in-memory limit. Motion
starts only after privacy/calibration and stops in the background; timers
and pending storage are flushed/re-armed on lifecycle changes. There is no
second gesture cooldown in the lens controller.

## SDK verification and image format

Verified against installed SDK **0.0.16** types and simulator behavior:
`waitForEvenAppBridge`, `createStartUpPageContainer`,
`rebuildPageContainer(new RebuildPageContainer(...))`,
`textContainerUpgrade(new TextContainerUpgrade(...))`,
`updateImageRawData(new ImageRawDataUpdate(...))`, `getLocalStorage`,
`setLocalStorage`, `onEvenHubEvent`, and `shutDownPageContainer(1)`.
Text and image container constructors, brightness, geometry and event enums
are typed. All render, storage, image, motion start/stop and audio start/stop
operations are serialized through the shared BridgeQueue. Long calibration
is not held inside that queue while waiting for gestures.

No unresolved `TODO(verify-sdk)` remains for an SDK call used by Part 1.
Part 2 owns the actual IMU APIs and axis/units characterization. No invented
IMU permission was added: the documented permission list has no such entry.

The temporary fixture sends **base64-encoded 288x144 RGBA PNGs** through
ImageRawDataUpdate. Both returned `success` and rendered the distinct 1/2
and 3/4 callouts in the actual simulator. This is Part 1's local PNG proof,
not a claim that Part 2's final tile transport or physical BLE timing is proven.

## Temporary stub and open requests

`app/src/ui/local-v2-stubs.ts` is an explicitly temporary section-6 adapter
per the role's bootstrap allowance. It uses no microphone, IMU, network,
provider key or real token. Mocks are not a claim of measured double-nod
detection, voice recognition or live assignment delivery.

When Part 2's v2 motion/client/capture modules land, main automatically
chooses those exact interfaces. At integration delete `local-v2-stubs.ts`,
remove its import/fallback in main and update its fixture-only tests to use
Part 2's mocks. Keep `taskFixture` in fixtures.ts for pure lens tests.

Open owner requests, also announced in the current chat:

1. **Part 2:** land section-6 v2 interfaces, mock endpoint/commands,
   pairing/assignments, simulateGesture and IMU replay. Confirm/adopt the
   PNG transport or provide the final proven format. Retry/offline progress
   delivery and real IMU behavior are untested integrations here.
2. **Companion owner:** add `command` to the tone and label maps in
   `ios/src/components/Pills.tsx` so `make test-ios` builds on contract v2.
3. **Part 3:** confirm the final relay origin. `app/app.json` remains exactly
   `https://45-32-88-132.sslip.io`; it was not switched to the root domain.
4. **Part 4:** the v1 sanitizer discrepancy remains an owner-coordination
   item. The lens fixture set and glyph behavior were not silently changed.

## Hardware

**Not yet tested on hardware.** The user confirmed no glasses are available.
STEP and DIAGRAM were visually inspected only in native simulator captures.
Default brightness, 14px label legibility, scan inversion, real IMU motion,
BLE transfer latency, and physical root exit remain device checks.
