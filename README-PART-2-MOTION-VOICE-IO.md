# Part 2 v2 — Head Gestures, Voice Endpointing & App I/O

**Branch:** `part-2-motion-voice-io`
**Read first:** `BUILD-PLAN-V2.md` (§3 interaction model, §4 diagrams, §5 contract).
**Owns:** everything that crosses the app's boundary: the IMU and the gesture
detector, the mic and the endpointer, the relay client for the new device /
task / progress / diagram routes, the mocks that unblock Part 1, and app Sentry.

**Milestones:** M0 (IMU recordings + image byte format, day one), M1
(hands-free ask with IMU replay), M2 (client v2 + mocks), M4 (hardware
false-positive test). You hold the two biggest unknowns in v2. Kill them first.

---

## 0. Before writing code

```
/plugin marketplace add even-realities/everything-evenhub
/plugin install everything-evenhub
```

Skills: `device-features`, `handle-input`, `sdk-reference`,
`test-with-simulator`, `build-and-deploy`. Verified in SDK 0.0.16 `dist/index.d.ts`:

```ts
bridge.imuControl(isOpen: boolean, reportFrq?: ImuReportPace): Promise<boolean>  // P100..P1000, default P100
// events: event.sysEvent.eventType === OsEventTypeList.IMU_DATA_REPORT (8)
//         event.sysEvent.imuData: { x?: number; y?: number; z?: number }
bridge.updateImageRawData({ containerID, containerName, imageData: number[] | string | Uint8Array }): Promise<ImageRawDataUpdateResult>
```

**What is not documented:** whether `x/y/z` are acceleration, angular rate or
Euler angles, their units, the axis orientation on the head, what the `P100..P1000`
pace codes mean in Hz, whether the simulator emits IMU events at all, and which
byte format `imageData` accepts. Do not guess any of these. Measure them.

## 1. Files you own

```
app/src/motion/imu.ts          # imuControl on/off, sample normalisation, foreground handling
app/src/motion/gestures.ts     # pure detector: samples -> NOD | SHAKE  (public surface below)
app/src/motion/calibrate.ts    # per-wearer thresholds, persisted via settings.ts
app/src/motion/record.ts       # dev-only recorder: dumps samples as JSON to the phone-side page
app/src/audio/capture.ts       # v2: onEndpoint
app/src/audio/vad.ts           # pure endpointer: rms frames -> speech_end | no_speech
app/src/api/client.ts          # v1 + pair / pairingStatus / nextAssignment / reportProgress / getDiagram
app/src/obs/sentry.ts          # + spans: gesture, endpoint, diagram_fetch
app/src/mock/                  # + IMU replay, mock assignment, mock diagram tiles, mock commands
app/src/settings.ts            # + device token, calibration, sensitivity, nod mode
app/tests/motion/fixtures/*.json   # recorded IMU sessions (motion only)
app/tests/gestures.test.ts, vad.test.ts, client.test.ts, audio.test.ts
```

## 2. Files you must NOT touch

`app/src/main.ts`, `state.ts`, `types.ts`, `ui/*`, `app.json`, `package.json`
(Part 1: ask for deps or permissions in the channel); `relay/`, `db/`,
`corpus/`, `eval/`, `portal/`, `ios/`, `Makefile`; and **`main`**.

Depend on `v2-scaffold-app` for `types.ts` (`git fetch --tags && git merge v2-scaffold-app`).
Until then paste BUILD-PLAN-V2 §5 into a temp `types.ts` and take Part 1's at merge.

---

## 3. Day one: the two unknowns

### 3a. IMU characterisation (on real glasses)

1. Build `record.ts`: `imuControl(true, pace)`, collect `{t, x, y, z}` for N
   seconds, print the JSON on the phone-side page (copy it off). Dev-only,
   behind `?dev=1`. **No audio, no names, nothing sent to the relay.**
2. Record at P100, P500 and P1000: still; 10 deliberate double nods; 10
   deliberate shakes; 2 min of scripted bench work (look down at the bench,
   up at a shelf, turn to a toolbox, read a gauge); 1 min walking; 30 s
   talking while nodding along.
3. From the data, write down in `app/HANDOFF.md`: what x/y/z are, units,
   which axis is pitch and which is yaw on the head, effective sample rate per
   pace code, and whether the simulator emits `IMU_DATA_REPORT`. Pick the
   lowest pace that still resolves a nod (battery). Commit the recordings to
   `app/tests/motion/fixtures/` — they are the test suite for the detector.
4. If the simulator emits no IMU events: the mock layer replays fixtures
   (`?imu=bench-work` or `?imu=double-nod`) and `simulateGesture()` exists for
   Part 1's dev buttons.

### 3b. Image byte format (simulator, then glasses)

Create one 288x144 image container (ask Part 1 for a throwaway branch commit
or do it in a scratch page), then try `updateImageRawData` with, in order:
PNG file bytes as `number[]`; raw 8-bit greyscale (41,472 bytes); raw 4-bit
packed (20,736 bytes). Record which return `success` and render correctly,
including which nibble is the left pixel. **Announce the winner to Part 4 the
same day**; it decides what `/v1/diagrams/{id}` tiles contain. Also time one
tile end to end over BLE on the glasses.

## 4. Gesture detector (`motion/gestures.ts`)

Pure function core, thin stateful wrapper:

```ts
export type HeadGesture = 'NOD' | 'SHAKE';
export function startHeadGestures(onGesture: (g: HeadGesture) => void): Promise<void>;
export function stopHeadGestures(): Promise<void>;
export function calibrate(onProgress: (done: number, needed: number) => void): Promise<{ ok: boolean }>;
export function isCalibrated(): boolean;
export function simulateGesture(g: HeadGesture): void;
// pure, for tests:
export function detect(samples: ImuSample[], params: DetectorParams): { t: number; g: HeadGesture }[];
```

Starting point (tune against the fixtures; every number is a knob in
`DetectorParams`, persisted per wearer by `calibrate`):

- Low-pass the pitch and yaw signals; work on the signal the characterisation
  says is angular (integrate rate if x/y/z are gyro; differentiate if angles).
- **Nod** = pitch dips below `-down` then returns past `+up` within
  300-900 ms, with yaw and roll quiet. **Double nod** = two nods with
  their peaks 250-1200 ms apart. Default trigger is the double nod; single-nod
  mode exists in settings but stays off until M4 data says it is safe.
- **Shake** = >= 2 yaw sign reversals with amplitude > `yaw` within 1 s, pitch quiet.
- **Motion gate:** when overall signal energy over the last 1 s exceeds
  `gate` (walking, bending, turning the whole body) emit nothing.
- **Cooldown** 1.5 s after any emitted gesture.
- `calibrate`: prompt for 3 double nods, set `down`/`up` at ~60 % of the
  wearer's median amplitude, keep the defaults if the wearer's nods are weak.
  Sensitivity slider in `settings.ts` scales all thresholds.

Tests run `detect()` over the committed fixtures:
`double-nod x10 -> 10 NOD`, `shake x10 -> 10 SHAKE`, `bench-work 2 min -> 0`,
`walking -> 0`, `talking-while-nodding` documented (whatever it is, write it down).

## 5. Endpointing (`audio/vad.ts` + `capture.ts`)

The press-to-send is gone, so capture has to know when the worker stopped.

- Per chunk, the RMS you already compute. Noise floor = median RMS of the first
  300 ms after the mic opens. Speech starts when RMS > floor x `k` (start ~3)
  for >= 150 ms; ends after 800 ms below it.
- `onEndpoint('speech_end')` -> Part 1 calls `stopCapture()` and sends.
  `onEndpoint('no_speech')` if no speech within 3 s -> `stopCapture()` returns
  `data_b64: ''` and nothing is sent. `onEndpoint('cap')` at 8 s, as v1.
- Trim leading silence before base64 (smaller upload, faster STT); keep 200 ms
  of pre-roll so the first word is not clipped.
- The SDK's `audioEvent.speakerRole` ('self' | 'other') may let us ignore a
  coworker talking nearby. Log it during the hardware pass; use it only if the
  data says it is reliable.
- Shop-floor noise will defeat a pure energy VAD sometimes. Fallbacks that must
  work: a second double nod or a tap sends immediately; shake cancels.
- Every v1 capture rule stands: mic open only between start and stop, 8 s
  cap, nothing persisted, re-check on `visibilitychange`.

## 6. Client v2 (`api/client.ts`)

Routes in BUILD-PLAN-V2 §5. Same rules as v1 (exact origin, timeouts, one
retry on network/5xx, never on 4xx, everything mapped to typed results).

- `pair()` on first boot; store `device_id` + `device_token` via
  `settings.ts` (the token is a credential for this device only; localStorage is
  the only storage we have and is sandboxed per `package_id`). Send
  `authorization: Bearer <device_token>` on every lens route. On 401: drop the
  token and re-pair.
- `nextAssignment()` returns `null` on 204. Part 1 polls it; you do not.
- `reportProgress(ev)`: append to an in-memory queue mirrored to
  localStorage (text only, cap 200 events, drop oldest), flush in one
  `POST /v1/progress` batch every 5 s or on 10 events, retry with backoff,
  flush on `FOREGROUND_EXIT_EVENT`. The relay is idempotent, so resending is safe.
- `getDiagram(id)`: in-memory LRU of 8 diagrams, de-dup concurrent fetches,
  return tiles already decoded into whatever `imageData` wants (§3b).
- `ask()`: v1, plus `context.assignment_id`. Validation addition: `outcome ===
  'command'` requires a known `command` value, else downgrade to `error`.

## 7. Mocks (`src/mock/`) — Part 1 lives on these

Extend the v1 fixture table (keyed by transcript substring):

| trigger | response |
|---|---|
| "next" / "done" | `command: next` |
| "back" | `command: back` |
| "diagram" / "show me" | `command: diagram` |
| "details" | `command: details` |
| "pause" | `command: pause` |

Plus: mock `pair()` (code `4F7K`, claimed after 5 s), mock `nextAssignment()`
(SOP-114 rev C as a 5-step task with a warning on step 1, a checkpoint on step
3 and diagrams on steps 2 and 3), mock `getDiagram()` returning generated test
tiles in the proven byte format, IMU replay, `MOCK_DELAY_MS`, and a mock
endpoint that fires `speech_end` 1.5 s after `startCapture`.

## 8. Build order

1. §3a recorder + recordings, §3b byte format. Announce both. (Day one.)
2. Mocks for Part 1 (§7). Push and tell Part 1.
3. `gestures.ts` `detect()` against the fixtures, test-first. Then the wrapper.
4. `vad.ts` against synthetic RMS sequences, then `capture.ts` v2.
5. Client v2 against Part 3's mock relay.
6. Hardware pass (M4): the false-positive protocol below.

## 9. Acceptance

- [ ] HANDOFF.md documents IMU axes/units/rates and the image byte format, with evidence.
- [ ] `detect()`: 10/10 double nods, 10/10 shakes, 0 triggers on the bench-work and walking fixtures.
- [ ] **M4 protocol, real glasses, two wearers:** 20 deliberate double nods
      each (>= 95 % detected); 30 min of scripted bench work each (<= 1 false
      trigger); nod -> LISTENING on the lens < 300 ms. Results in HANDOFF.md.
- [ ] A false trigger with nobody speaking sends nothing (assert no `ask` call).
- [ ] "next" spoken -> new step, p50 < 1.2 s end-of-speech to lens (with Part 3's fast path).
- [ ] Progress survives airplane mode for 2 min and flushes on reconnect; no duplicates on the board.
- [ ] Mic provably closed outside LISTENING (log every `audioControl`); IMU off in background (log every `imuControl`).
- [ ] Every v1 Part 2 acceptance item still passes.

## 10. House rules

Every v1 rule (BUILD-PLAN-V2 §8). Raw audio never persisted. IMU samples never
sent to the relay. The detector is a calibration problem as much as a code
problem; leave every threshold as a named, persisted knob. Do **not** add
`Co-Authored-By: Claude` to commits.
