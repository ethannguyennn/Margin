# Part 2 handoff: motion, voice and app I/O (v2)

Branch `part-2-motion-voice-io`. Final tested code commit: **`6f25d28`** (this document is
the commit after it). Date: 2026-10-17.

**Status in one line:** everything fixture- and mock-driven is built and tested. **No
hardware results exist yet**: the loaned glasses were not available in this session. Every
hardware number below is marked MISSING. No detection rate here was measured on a person.

---

## 1. Day-one finding #1: IMU semantics

| Question | Answer | Evidence |
|---|---|---|
| What x/y/z are (angle, rate, acceleration) | **Unknown: MISSING (glasses)** | SDK 0.0.16 `IMU_Report_Data` only has `x?/y?/z?: number` ("double on wire"). The official docs ([device APIs](https://hub.evenrealities.com/docs/build/device-apis)) call them "X-axis value", with no units |
| Units | **Unknown: MISSING** | Same sources |
| Which axis is pitch, which is yaw | **Unknown: MISSING** | No published head frame |
| Effective sample rate per pace code | **Unknown: MISSING** | Docs: "protocol pacing codes, not literal Hz values" |
| Does the simulator emit `IMU_DATA_REPORT`? | **No. It does not implement `imuControl` at all.** | evenhub-simulator **0.9.5**: calling `bridge.imuControl(true, P100)` logs `[uncaught] Uncaught unknown variant 'imuControl', expected one of 'getUserInfo', 'getGlassesInfo', 'setLocalStorage', 'getLocalStorage', 'createStartUpPageContainer', 'rebuildPageContainer', 'updateImageRawData', 'textContainerUpgrade', 'shutDownPageContainer', 'audioControl'`, and **the promise never settles**. 0 events at P100/P500/P1000 |

Consequences already in the code:

- `motion/imu.ts` races every `imuControl` call against a 1.5 s timeout, so the app can't hang
  in the simulator or on a host that never answers.
- Under `VITE_MOCK=1` the IMU is never opened. Use `?imu=<fixture>` replay or `simulateGesture()`.
- The detector does not hard-code the IMU's meaning. `DetectorParams.pitchAxis/pitchSign/yawAxis/
  yawSign/signal('angle'|'rate')/scale/wrap` are the knobs that the recording fills in.
  `DEFAULT_PARAMS` are **provisional** placeholders (pitch=x, yaw=y, angles in degrees) and must be
  set from the recordings.
- Protobuf omits zero-valued fields, so a missing axis is read as 0 (`toSample`).
- No app.json permission exists for the IMU (valid names: network, location, g2-microphone,
  phone-microphone, album, camera), so Part 1 has nothing to add.

### How to finish it on the glasses (about 30 min)

1. Part 1 adds this one line to `main.ts`, after the startup page exists:
   `if (new URLSearchParams(location.search).has('dev')) import('./motion/record.ts').then(m => m.mountRecorder(document.body));`
2. Open the app with `?dev=1`, pick a pace, an activity and wearer letter **A** or **B** (never a name),
   then Record. The page prints the fixture JSON plus a `characterize()` summary: `hz`,
   `dt_median_ms`, `burst_frac`, per-axis mean/std/range, `|v|` mean/std, `dominant_axis`, and a hint
   (|v| ≈ 9.8 or ≈ 1 when still means an accelerometer; axes centred on 0 mean a rate; steady offsets
   mean angles).
3. Protocol per pace (P100, P500, P1000): still 30 s; 10 double nods; 10 shakes; 2 min of scripted
   bench work; 1 min walking; 30 s talking while nodding.
4. Save each file as `app/tests/motion/fixtures/<activity>.g2-<wearer>-P<pace>.json`, and add
   `"expect": {"NOD":10,"SHAKE":0}` (etc.) to `meta`. `gestures.test.ts` picks every fixture up
   automatically. If an axis mapping differs from the defaults, update `DEFAULT_PARAMS`, not the
   fixtures.
5. Fill in the table above and pick the lowest pace that still passes (battery).

---

## 2. Day-one finding #2: image byte format

**Simulator result (evenhub-simulator 0.9.5)**, probe `docs/handoffs/part-2/byte-format-probe.ts`.
Four 288x144 image containers, one test pattern: a 16-level gradient, alternating even/odd columns
for nibble order, and a left marker for flips. Framebuffer read back through `/api/screenshot/glasses`.

| Format sent to `updateImageRawData` (as `number[]`) | Bytes | Result | Renders correctly? |
|---|---|---|---|
| **PNG** (8-bit greyscale, values = level x 17) | 1,753 | `success` | **Yes**: all 16 levels, columns and orientation exact |
| **Packed 4-bit, high nibble = left pixel**, row-major | 20,736 | `success` | **Yes**: even columns lit for `0xF0` bytes, so the **high nibble is the left pixel** |
| Raw 8-bit grey, value = level x 17 | 41,472 | `success` | Yes |
| Raw 8-bit grey, value = level << 4 | 41,472 | `success` | Yes (one band off by a level) |
| Raw 8-bit grey, value = level (0..15) | 41,472 | `success` | Yes (!) |
| Raw 8-bit grey, hi = level, lo = 15 - level | 41,472 | `success` | **No**: byte 15 rendered full-bright, levels shifted |

Evidence: `docs/handoffs/part-2/byte-format-sim-round1.png` and `-round2.png` (tiles A = PNG,
B = 8-bit, C = packed, D = 8-bit variant). In the readback, alpha by level saturates at level 9:
`0,96,131,157,179,197,214,230,244,255...`. That is the simulator's display curve.

**Decision (announced to Part 4): tiles are 8-bit greyscale PNG**, 288x144 (or the tile's own
width/height), with every pixel already quantised and dithered to the 16 lens levels (`level * 17`),
base64 in `DiagramImage.tiles[].image`.

Why:
- The host clearly decodes encoded images (`imageToGray4Failed` in the result enum, and the PNG
  was accepted by content rather than by length).
- Raw 8-bit is ambiguous (the host's byte-to-level mapping is inconsistent).
- PNG doubles as the portal preview.

**Proven fallback:** packed 4-bit, high nibble = left pixel. `client.getDiagram` accepts both.
It checks for the PNG signature, otherwise requires `width*height/2` bytes, and hands Part 1
`tile.bytes` as `number[]`, the form the SDK recommends.

**MISSING (glasses):**
- Confirm PNG renders on the real lens (the SDK is obfuscated with no LZ4 inside, so
  conversion happens in the phone host, and the simulator is a separate implementation).
- Measure BLE time for one tile. In the simulator `updateImageRawData` took 6-59 ms per tile, which
  says nothing about BLE.
- Mock tiles use stored (uncompressed) deflate and are ~41.7 KB each. Part 4's Pillow PNGs will be
  far smaller.

---

## 3. Detector (`app/src/motion/gestures.ts`)

One streaming `Detector` serves both the pure `detect()` (tests) and the live `startHeadGestures()`.
Pipeline:
1. Raw axes → (differentiate if `signal: 'angle'`, with ±180° wrap) → rate in °/s.
2. Low-pass filter, plus optional gyro bias removal.
3. Lobes: a lobe opens when |rate| crosses its threshold and closes below `lobeEnd x threshold`.

Gestures:
- **Nod** = a down lobe (≤ −`down`), then an up lobe (≥ `up`) starting 60-600 ms later, with peak
  yaw and roll < 0.6 x peak pitch.
- **Double nod** = two nods 250-1200 ms apart. This is the default trigger, emitted as `NOD`.
- **Shake** = 3 alternating yaw lobes (≥ 2 reversals) within 1 s, with peak pitch < 0.6 x peak yaw.
- **Motion gate** = RMS of the all-axis rate over the 700 ms ending 200 ms before onset must be
  ≤ `gate`.
- **Cooldown** 1.5 s.
- BLE bursts (duplicate timestamps) use the running mean dt. A gap > 300 ms resets.

| Knob | Default | Note |
|---|---|---|
| pitchAxis / pitchSign / yawAxis / yawSign | x / +1 / y / +1 | **PROVISIONAL**, from the recordings |
| signal / scale / wrap | angle / 1 / 360 | **PROVISIONAL** |
| lpMs / hpMs | 40 / 0 | set hpMs ≈ 2000 if x/y/z turn out to be a biased gyro |
| down / up | 50 / 40 °/s | calibrated per wearer |
| nodMinMs / nodMaxMs | 60 / 600 | down-lobe onset → up-lobe onset |
| doubleMinMs / doubleMaxMs | 250 / 1200 | |
| yaw / shakeMs | 50 °/s / 1000 | 80 missed half the Hann-windowed shakes |
| quietRatio | 0.6 | |
| gate / gateMs / gateLeadMs | 20 °/s / 700 / 200 | the lead stops a gesture's own wind-up from gating it |
| cooldownMs / maxGapMs / lobeEnd | 1500 / 300 / 0.3 | |
| single | false | `settings.setNodMode('single')`; stays off until M4 |

**Calibration** (`calibrate(onProgress)`):
- Asks for 3 double nods, detected with half thresholds, no gate and no cooldown.
- Sets `down`/`up` = 0.6 x the wearer's median peak rate, and persists them through
  `settings.setDetectorOverrides`.
- If that falls below 0.6 x the defaults, the nods are too weak: it keeps the defaults and returns
  `{ ok: false }`. It also returns `{ ok: false }` after a 30 s timeout.

**Sensitivity** (`settings.setSensitivity`, 0.5-2) divides `down`/`up`/`yaw`. The gate is not
scaled: a more sensitive trigger shouldn't also make the gate stricter.

### Fixture results (SYNTHETIC, not hardware)

The fixtures come from `tests/motion/synth.ts`: a seeded model of head Euler angles at 50 Hz with
BLE jitter and bursts, minimum-jerk movements, nods of 12-22° and shakes of 15-28°.

| Fixture | NOD | SHAKE | Expected |
|---|---|---|---|
| double-nod.synthetic (10 double nods) | **10** | 0 | 10 / 0 |
| shake.synthetic (10 shakes) | 0 | **10** | 0 / 10 |
| bench-work.synthetic (2 min: bench, shelf, toolbox, gauge, 5 quick single glances, coworker) | **0** | 0 | 0 / 0 |
| walking.synthetic (1 min, 3.5° bob at ~1.9 Hz, heel jolts, 2 turns) | **0** | 0 | 0 / 0 |
| still.synthetic (30 s) | 0 | 0 | 0 / 0 |
| talking-nodding.synthetic (30 s of 4-9° nods every 0.6-1.4 s) | 0 | 0 | documented |

Also covered:
- The same nods as angular rate (`signal:'rate'`), in radians (`scale: 180/π`), with swapped axes,
  near ±180° and with bursts: 10/10 each.
- At 25 Hz: 10/10 (asserted). At 12.5 Hz: 10/10 (logged).

**These numbers validate the logic against a model. They say nothing about real wearers.**

---

## 4. Voice endpointing (`audio/vad.ts`, `audio/capture.ts`)

**Parameters (`DEFAULT_VAD`):**
- Noise floor = median RMS of the first 300 ms, clamped to [0.003, 0.05], and allowed to track down
  later.
- Speech = RMS > 3 x floor for ≥ 150 ms.
- `speech_end` after 800 ms below threshold.
- `no_speech` if nothing by 3 s.
- `cap` at 8 s (v1).

**Behaviour:**
- `onEndpoint` fires once per press and the mic closes immediately; Part 1 then calls
  `stopCapture()`.
- After `no_speech`, `stopCapture()` returns `data_b64: ''`, so Part 1 must not ask (tested: zero
  fetches).
- Leading silence is trimmed, keeping 200 ms of pre-roll.
- A manual stop (tap or second double nod) before the VAD saw speech sends everything, because a
  loud shop can defeat the energy VAD (tested).
- `speakerRole` is tallied per press in the `audioControl(false)` log line. It is not used for
  filtering. **MISSING:** the hardware data on whether it is reliable.

---

## 5. Client v2 (`api/client.ts`) and mocks

**Lens route behaviour:**
- `pair()`, `pairingStatus()`, `nextAssignment()` (204 → `null`), `reportProgress(ev)` and
  `getDiagram(id)` all use `VITE_RELAY_ORIGIN` and `authorization: Bearer <device_token>`.
  `ask` also sends the token when paired.
- One retry on network errors and 5xx, never on a 4xx.
- On a 401 the token is dropped and the call rejects with `RelayError` code `'unauthorized'`;
  Part 1 then calls `pair()`. Other failures reject with `RelayError` codes `bad_request`,
  `not_found`, `server_error`, `network` or `timeout`.

**Progress queue:**
- Text only, capped at 200 (oldest dropped), mirrored to `localStorage['margin.progressQueue']`.
- Flushed as one batch every 5 s or on the 10th event, and on `FOREGROUND_EXIT_EVENT`, on hide and
  on `online`.
- Backs off 5 → 60 s while offline. A 4xx batch is dropped.
- Only the events actually sent are removed, so nothing is duplicated. The 2-min airplane-mode
  replay is tested with fake timers.

**Diagrams:** an LRU of 8, concurrent fetches de-duplicated, tiles validated and decoded to
`tile.bytes`. A prefetch nobody awaits never becomes an unhandled rejection.

**Command validation:** an `outcome: 'command'` response must carry a known `command`, otherwise it
becomes `error`/`bad_request`. Command responses are stripped of text. `needs_clarification` is
passed through.

**Mocks (`VITE_MOCK=1`):**
- Whole-utterance command fixtures for all 8 commands. "what's the next step's torque" stays a
  question.
- `queueMockTranscripts(...)` sets what the next audio asks "hear".
- Pairing: code **4F7K**, claimed 5 s after the first `pair()`.
- Assignment: SOP-114 rev C, 5 steps, warning on step 1, checkpoint on step 3, diagrams on steps 2
  and 3 (`dg-sop114-guard`, `dg-sop114-bracket`). It is withheld after `task_completed`.
- Diagram tiles are PNGs in the proven format.
- Mock endpoint fires `speech_end` at 1.5 s; `setMockEndpoint('no_speech')` makes it return `''`.
- `MOCK_DELAY_MS` (`setMockDelayMs`); commands and pairing run at a third of the delay.
- IMU replay: `?imu=<fixture>`. `simulateGesture()` drives dev buttons.

**Simulator run under `VITE_MOCK=1`** (throwaway harness, not committed):
- `?imu=double-nod` replay produced 10 live `NOD`s over 38 s.
- `pair` returned 4F7K, then the assignment arrived after the claim.
- `getDiagram('dg-sop114-bracket')` passed through `updateImageRawData`: `success` x2. Screenshot:
  `docs/handoffs/part-2/mock-diagram-sim.png`.
- Progress flushed.
- The mock endpoint led to `ask` returning `outcome=command command=next`.

**Sentry spans:** `gesture`, `endpoint` (from mic open), `diagram_fetch` (with outcome), via
`obs.span()`. They are no-ops without a DSN.

---

## 6. Results recorded

| Check | Result |
|---|---|
| `npm test` (app) | **262 passed, 6 skipped** (the skipped tests are the relay e2e). v1 baseline was 202 passed, so all v1 tests still pass |
| `tsc --noEmit`, `vite build` | clean |
| `gestures.test.ts` | 23 passed: 6 fixtures + 17 logic/wrapper/calibration |
| `vad.test.ts` | 10 passed |
| `audio.test.ts` | 14 passed (9 v1 + 5 v2 endpoint) |
| `client.test.ts` | 35 passed (v1 + v2 routes, queue, diagrams, mocks) |
| Mutation check | Breaking the queue's drop or setting silence to 700 ms fails 7 tests |
| `relay.e2e.test.ts` against Part 3's current relay (`MOCK_MODE=1`, v1 routes) | **6 passed** with the v2 client |
| Client v2 against Part 3's **v2** mock relay | **MISSING**: `POST /v1/devices/pair` returns 404 on the current relay; Part 3 has not pushed v2 routes |
| M4 wearer A: 20 double nods / 30 min bench / nod→LISTENING | **MISSING** (no glasses) |
| M4 wearer B: same | **MISSING** |
| False trigger with nobody speaking makes no ask | tested in code (`audio.test.ts`, 0 fetches). **MISSING** on hardware |
| "next" p50 < 1.2 s end of speech → lens | **MISSING** (needs Part 3 fast path + glasses) |
| Progress survives 2 min airplane mode, no duplicates | tested with fake timers. **MISSING** on device + relay board |
| TODO.md §3 v1 hardware checks (transcript ≤ 2 s, mic closed outside LISTENING + 8 s cap, lock 5 min, permission denied, glasses vs phone mic A/B) | **MISSING** (glasses). The code paths are unit-tested and every `audioControl`/`imuControl` call is logged |

---

## 7. Commands

```bash
cd app
npm test                                         # everything
npx vitest run tests/gestures.test.ts --reporter=verbose --silent=false   # prints the fixture table
node tests/motion/synth.ts                       # regenerate the synthetic fixtures (deterministic)
npm run dev:mock                                 # then open the simulator on
npx evenhub-simulator "http://localhost:5174/?imu=double-nod" --automation-port 9898   # IMU replay (also bench-work, shake, walking...)
# v1 relay contract e2e:
#   (relay) MOCK_MODE=1 ALLOWED_ORIGINS=http://localhost:5174 uvicorn margin_relay.main:create_app --factory --port 8091
MARGIN_E2E_RELAY=http://127.0.0.1:8091 npx vitest run tests/relay.e2e.test.ts
# Recorder on glasses: open the app with ?dev=1 (after Part 1 adds the mount line, §1)
```

Byte-format probe: copy `docs/handoffs/part-2/byte-format-probe.ts` to `app/_probe.ts`, then
serve a one-line `_probe.html` that loads it. Open it in the simulator or on the glasses and read
the `[probe]` console lines and screenshot. Delete it afterwards.

---

## 8. Limitations and open requests

**Open requests to Part 1:**
- Take Part 1's `types.ts` at the `v2-scaffold-app` merge. Mine is a verbatim copy of §5.
- Wiring:
  - `startCapture(onLevel, onEndpoint)`: on `speech_end`/`cap` call `stopCapture()` then
    `ask`; on `no_speech` call `stopCapture()` and return silently.
  - Gestures go to `controller.dispatch`. Run `startHeadGestures` after PRIVACY and stop/start it
    on foreground exit/enter (imu.ts also self-closes on exit and hidden).
  - Add the `?dev=1` recorder mount line.
- To use `tile.bytes`, import `LensDiagram` from `api/client.ts`. It is a structural superset of
  `DiagramImage`.
- No new dependencies. No app.json changes are needed for v2. `phone-microphone` is only needed
  if the phone-mic A/B ships.

**Open request to Part 3:** v2 routes on the mock relay so `pair` / `me` / `assignments/next` /
`progress` / `diagrams` can be run end to end. The relay must answer 204 on no assignment and 401
on a bad token.

**Open request to Part 4:** render PNG tiles as in §2, and send me one real tile to time over BLE.

**Limitations:**
- All detector defaults and the axis/units mapping are unvalidated on hardware.
- The synthetic fixtures are a model and can be wrong in ways that matter: real walking may excite
  pitch more, and a real gyro may drift.
- The energy VAD's `k` / `maxFloor` are untuned against glasses-mic levels.
- `talking-nodding` produced 0 triggers in the model only. Gestures except shake are ignored while
  LISTENING anyway (Part 1).
- Not started, per scope: single-nod mode tuning, speakerRole filtering, battery tuning beyond pace
  choice.
