# Part 1 v2 — Hands-free Lens UI & State Machine

**Branch:** `part-1-lens-hands-free-ui`
**Read first:** `BUILD-PLAN-V2.md` (§3 interaction model, §4 diagrams, §5 contract).
**Owns:** everything the worker sees on the G2, the state machine that turns
gestures + voice commands + relay responses into screens, and `types.ts`.

**Milestones:** M0 (`v2-scaffold-app` tag), M1 (hands-free ask loop), M2
(task + diagram in the simulator), M4 (hardware legibility + UX pass).

---

## 0. Before writing code

```
/plugin marketplace add even-realities/everything-evenhub
/plugin install everything-evenhub
```

Skills: `glasses-ui`, `handle-input`, `device-features`, `test-with-simulator`,
`sdk-reference`, `design-guidelines`. **Do not invent SDK APIs.** Verified so
far against `@evenrealities/even_hub_sdk` 0.0.16 `dist/index.d.ts`:
`rebuildPageContainer(RebuildPageContainer): Promise<boolean>`,
`updateImageRawData({containerID, containerName, imageData}): Promise<ImageRawDataUpdateResult>`,
`ImageContainerProperty {xPosition, yPosition, width 20-288, height 20-144, containerID, containerName, zOrderIndex?}`.
Anything else: `// TODO(verify-sdk)` and keep going.

## 1. Files you own

```
app/app.json                  # permissions (+ IMU if the SDK requires one: VERIFY), whitelist
app/src/main.ts               # boot, wiring of Part 2's new modules, dev gesture buttons
app/src/state.ts              # v2 states, transitions, persistence
app/src/types.ts              # SHARED contract v2 (BUILD-PLAN-V2 §5), verbatim
app/src/ui/layout.ts          # TEXT layout + DIAGRAM layout, rebuild only on layout switch
app/src/ui/screens.ts         # one render fn per screen
app/src/ui/input.ts           # tap events -> Gesture (unchanged mapping, plus NOD/SHAKE passthrough)
app/src/ui/paginate.ts, glyphs.ts, bridge-queue.ts, session-store.ts, fixtures.ts
app/tests/state.test.ts, display.test.ts, controller.test.ts, glyphs/paginate tests
app/HANDOFF.md
```

## 2. Files you must NOT touch

`app/src/audio/`, `app/src/api/`, `app/src/motion/`, `app/src/obs/`,
`app/src/mock/`, `app/src/settings.ts` (Part 2); `relay/`, `db/`, `corpus/`,
`eval/`, `portal/`, `ios/`, `Makefile`; and **`main`**.

---

## 3. Contract (do this first, hour one)

Paste BUILD-PLAN-V2 §5 TypeScript into `types.ts` verbatim. Keep v1 behaviour
for every v1 field. Commit, then:

```
git tag v2-scaffold-app && git push origin part-1-lens-hands-free-ui --tags
```

and announce it. Part 2 and the iPhone companion (`ios/src/contract.ts`
re-exports your file) build on it.

## 4. State machine v2 (`state.ts`)

Keep it a pure transition table with effects, as in v1. New screens:

| Screen | Shows | Entered from |
|---|---|---|
| `CALIBRATE` | "Nod twice now (2/3)" | first run after PRIVACY, or voice "calibrate" later (stretch) |
| `PAIRING` | "Pair code 4F7K / enter it in the Margin portal" | boot when the device is unclaimed |
| `TASK_READY` | "Task ready: Pump seal swap / 6 steps / nod twice to start" | `nextAssignment()` returned a task while IDLE |
| `STEP` | progress bar, step glance, warning line, checkpoint, `[diagram]` hint | task start, `next`/`back`/`resume`, back from DETAILS/DIAGRAM/answers |
| `STEP_DETAILS` | paginated step body (v1 ANSWER_EXPANDED for a step) | `details` command or tap on STEP |
| `DIAGRAM` | diagram (2 image tiles) + caption | `diagram` command, or swipe down on STEP when a diagram exists |
| `TASK_DONE` | "Task complete. 6/6 steps" | `next` on the last step |

Plus every v1 screen. Rename v1 `WALKTHROUGH` to `STEP` internally; a v1
"walk me through" response still lands on `STEP` (no `assignment_id`, no
progress events).

New actions: `NOD`, `SHAKE`, `ENDPOINT` (Part 2's capture says speech ended
or no speech), `ASSIGNMENT {assignment}`, `PAIRED`, `DIAGRAM_READY {id}`.

New effects: `REPORT_PROGRESS {kind, step_id}`, `PREFETCH_DIAGRAMS`,
`SHOW_DIAGRAM {diagram_id}`, `POLL_ASSIGNMENT`.

Rules:

- **`returnTo`.** LISTENING and THINKING remember the screen they came from.
  SHAKE in LISTENING, NOT_FOUND / ERROR dismissal and any answer dismissal
  return there, not to IDLE. A worker mid-task must never be dropped to IDLE by
  asking a question. Unit-test this for every screen.
- **Commands are local.** `outcome === 'command'` maps `command` onto the
  transition table; nothing else in that response is rendered. `next` on a
  step emits `REPORT_PROGRESS step_completed` then `step_started` for the next.
- **Gesture gating.** Ignore NOD in LISTENING/THINKING; ignore SHAKE on STEP
  and TASK_READY; 1.5 s cooldown is Part 2's, do not duplicate it.
- **Timeouts.** STEP, STEP_DETAILS, DIAGRAM, TASK_READY: none. Answers over a
  step: 20 s, then back to the step. IDLE answers: as v1.
- **Persistence.** Add `assignment_id` and the device token (Part 2 stores the
  token via `settings.ts`; you persist only `assignment_id` + index). Restore an
  assigned task if < 12 h old (a shift), a v1 ad-hoc walkthrough if < 30 min.
- **Never display unverified text.** Unchanged. Step text from an assignment
  was verified and approved at authoring time; it is trusted because it came
  from `/v1/assignments/next`, not from `/v1/ask`.

### Gesture map v2

| Input | IDLE | TASK_READY | STEP | STEP_DETAILS | DIAGRAM | LISTENING | answer screens |
|---|---|---|---|---|---|---|---|
| Double nod | listen | start task | listen | listen | listen | - | listen |
| Shake | - | - | - | back to STEP | back to STEP | cancel -> returnTo | dismiss -> returnTo |
| Tap | listen | start task | details | page / back | back | send | v1 |
| Swipe up/down | - | - | prev/next step | page | - | - | v1 |
| Double tap | **exit** | IDLE | pause -> IDLE | back | back | cancel | v1 |

## 5. Layouts (`layout.ts`)

Two container sets. Rebuild **only** when switching between them.

```
TEXT (v1, unchanged)                    DIAGRAM
 header  text  y 0-40    brightness 2    header   text   y 0-40     brightness 2
 main    text  y 48-232  capture, 4      tile-0   image  x 0,   y 48, 288x144
 footer  text  y 240-288 brightness 2    tile-1   image  x 288, y 48, 288x144
                                         footer   text   y 240-288  capture, brightness 3
```

- Exactly one `isEventCapture: 1` per layout. In DIAGRAM the footer captures,
  so `input.ts` must accept taps from the footer's container ID in that layout.
- No `zOrderIndex` anywhere (all-or-none rule), unless you need overlap.
- Sequence: `rebuildPageContainer(DIAGRAM)` -> `updateImageRawData(tile-0)` ->
  `updateImageRawData(tile-1)` -> caption via `textContainerUpgrade`. Image
  updates go through the same `BridgeQueue` as text; never two in flight.
- If the diagram bytes are not cached yet, show the caption + "loading
  diagram" and swap in the tiles on `DIAGRAM_READY`. Any image result other
  than `success`: back to STEP with "Diagram unavailable" in the footer.
- `STEP` text budget: header `SOP-150 rev A  3/6 ━━━━━─────`; main: glance
  (<= 60), blank line, `! <warning>` (<= 80), `> <checkpoint>` (<= 60); footer
  `nod: speak   [diagram]` only when the step has one.

## 6. Interfaces you consume (Part 2 implements; mock under `VITE_MOCK=1`)

```ts
// app/src/motion/gestures.ts
export type HeadGesture = 'NOD' | 'SHAKE';
export function startHeadGestures(onGesture: (g: HeadGesture) => void): Promise<void>;
export function stopHeadGestures(): Promise<void>;
export function calibrate(onProgress: (done: number, needed: number) => void): Promise<{ ok: boolean }>;
export function isCalibrated(): boolean;
export function simulateGesture(g: HeadGesture): void;    // dev buttons + tests

// app/src/audio/capture.ts (v2: onEndpoint added; v1 calls still work)
export function startCapture(onLevel: (rms01: number) => void,
  onEndpoint?: (reason: 'speech_end' | 'no_speech' | 'cap') => void): Promise<void>;
export function stopCapture(): Promise<{ data_b64: string; sample_rate: 16000 }>;  // data_b64 '' when no speech
export function isCapturing(): boolean;

// app/src/api/client.ts (v1 ask/health/logDeviation unchanged)
export function pair(): Promise<Pairing>;
export function pairingStatus(): Promise<Pairing>;
export function nextAssignment(): Promise<Assignment | null>;
export function reportProgress(ev: ProgressEvent): void;        // fire-and-forget, queued + retried by Part 2
export function getDiagram(diagram_id: string): Promise<DiagramImage>;  // cached; prefetch = call and ignore
```

`stopCapture()` returning `data_b64: ''` means **do not call `ask`**: go back
to `returnTo` silently.

Wire IMU gestures through `controller.dispatch({ type: 'NOD' })`. Start head
gestures after the startup page exists and after PRIVACY; stop them on
`FOREGROUND_EXIT_EVENT`, restart on enter.

## 7. Build order

1. `types.ts` v2 + tag (hour one).
2. `state.ts` transitions + tests for every new screen x input, `returnTo`
   for every screen, command mapping, restore rules. Pure, no SDK.
3. `layout.ts` DIAGRAM layout + rebuild logic with a fake bridge; test that
   content-only changes never rebuild and layout switches always do.
4. `screens.ts` for the new screens, fixture-driven.
5. `main.ts`: wire Part 2's motion module, `onEndpoint`, polling
   `nextAssignment` every 10 s while IDLE (stop while in a task), pairing on
   boot, prefetch on every step change. Dev-only "Nod" / "Shake" buttons on the
   phone-side page calling `simulateGesture` (hidden unless `VITE_MOCK=1` or
   `?dev=1`).
6. Simulator evidence (extend `tests/simulator-smoke.mjs`): M1 and M2 loops.
7. Hardware: diagram legibility (line weight, 14 px label floor, inverted
   scans), brightness levels, the new STEP layout at arm's length.

## 8. Acceptance

- [ ] **M1:** simulator, `VITE_MOCK=1`, dev Nod button only: IDLE -> LISTENING
      -> (mock endpoint) THINKING -> ANSWER_GLANCE -> 20 s -> IDLE. Zero taps.
- [ ] **M2:** mock assignment arrives -> TASK_READY -> nod -> STEP 1 -> "next"
      x2 -> STEP 3 -> "show diagram" -> DIAGRAM with two tiles -> shake -> STEP 3.
      Progress events logged in order.
- [ ] A question asked from STEP 3 returns to STEP 3 after the answer, NOT_FOUND
      or ERROR. Cold start mid-task restores STEP 3.
- [ ] `rebuildPageContainer` is called only on TEXT <-> DIAGRAM switches
      (assert with a call counter).
- [ ] `outcome: 'command'` never renders text. Unverified answers never render.
- [ ] Double tap on root still exits. Every v1 acceptance test still passes.
- [ ] Hardware: diagram readable at the default brightness; recorded in HANDOFF.md.

## 9. House rules

Every v1 rule (BUILD-PLAN-V2 §8). The lens is quiet by default: a task step is
the only thing that stays on screen without a timeout. Do **not** add
`Co-Authored-By: Claude` to commits.
