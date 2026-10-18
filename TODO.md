# Specs TODO

Updated 2026-10-17 after **all five v2 parts were merged into `main`** (order 1, 3, 2, 4, 5, on
top of the phone-UI merge from PR #3) and the cross-part follow-ups were closed.
Windows: `make` = `mingw32-make`.

**Where we are:** `main` holds v2 end to end on mocks.

- **Tests:** `make test` is green: relay 652 passed (11 opt-in live/PG skipped, 0 xfail), app
  546 passed + typecheck + build, portal 8 passed + build.
- **Simulator, mock app:** Part 1's v2 smoke runs on Part 2's real mocks (M1, M2, returnTo,
  native exit, cold start; 25 screen assertions).
- **Simulator, live app vs. Part 3's v2 relay (`MOCK_MODE=1`):** pairing → supervisor claim →
  assignment → TASK_READY → STEP → progress on the board → relay diagram DGM-0001 rendered in
  both tiles.
- **Client v2 e2e:** 12/12 against that relay.
- **Live Postgres tests:** 3/3 on a local PG17 + TimescaleDB + pgvector.
- **Not done yet:** nothing v2 is deployed (the live relay is the v1 build) and **nothing has
  run on glasses.**

---

## 1. Deploy (Part 3)

- [ ] **Deploy v2 to the VM** (`make deploy`): relay + Caddy with the portal at `/portal/`. Add
      `PORTAL_TOKEN` and `GEMINI_MODEL_CONVERT` to the VM's `.env` first ([[deploy/README]]).
      Today both `https://45-32-88-132.sslip.io` and `https://getyourassto.work` serve the
      **v1** build (`/v1/devices/pair` and `/portal/` are 404)
- [ ] **Domain switch:** the root domain already answers over TLS. After the v2 deploy, build the
      app with `VITE_RELAY_ORIGIN=https://getyourassto.work`. `app.json` already whitelists both
      origins - Parts 1 + 3
- [ ] **From a phone on cellular:** `https://getyourassto.work/v1/health` and `/portal/`
- [ ] **Device CORS origin:** read the `CORS rejected origin` WARN line when the glasses first call
      the relay; add that exact origin to `ALLOWED_ORIGINS`
- [ ] **`make latency`** on real traffic; report `intent='command'` rows separately (target:
      command = STT + < 50 ms, answer p50 <= 3 s)
- [x] **Live database (2026-10-17):** both migrations applied on Tiger; the demo bank (SOP-201..230 rev C,
      134 chunks) is seeded and the HX-2 rows removed (backup outside the repo:
      `db-backups/hx2-bank-2026-10-17.json`). The live v1 relay answers from it
- [ ] **Opt-in live tests on Tiger** (`SPECS_TEST_V2_DATABASE=1`, `DATABASE_URL`) - Part 5

## 2. Open requests between parts

- [ ] **Parts 3 + 5 - walkthrough citations:** `ask.py` builds walkthrough citations with
      `quote=step.body`. For authored v2 steps the body may paraphrase; the verbatim support is the
      published chunk's `text` (the joined source quotes). Cite that instead (needs `steps_for` /
      `build_walkthrough` to expose it, since `Step` has no quote field)
- [ ] **Part 4 - model + quota:** `gemini-3.8-flash` hit the free-tier daily cap (429); a paid key is
      needed before the M3 demo. On `gemini-3.5-flash-lite` SOP-153 converted with every value
      kept but **no schematic** for the star-pattern step
- [ ] **Phone screen in mock mode:** with `VITE_MOCK=1` the lens uses Part 2's mocks, but the phone
      screen's procedures/steps/deviation calls still go to the relay. Run a `MOCK_MODE=1` relay
      alongside - Parts 2 + 3
- [ ] **Base44:** `ios/` came from a Base44 project (`ios-base-44`). If Base44 still syncs to that
      folder, point it at `app/` or stop syncing, or it may recreate `ios/` - owner of PR #1

## 3. Hardware (glasses + phone) - Parts 1 + 2

Protocols and the recorder are in `docs/handoffs/PART-2.md`. Open the dev server with `?dev=1`
for the IMU recorder.

- [ ] **IMU characterisation:** x/y/z meaning, units, axes, Hz per pace code. Record still, double
      nods, shakes, bench work, walking and talking at P100/P500/P1000; set `DEFAULT_PARAMS` in
      `motion/gestures.ts`; commit the fixtures
- [ ] **PNG tiles on the real lens** + BLE time per tile (Part 4's four real tiles too)
- [ ] **M4, two wearers:** 20 double nods each (>= 95 %), 30 min bench work each (<= 1 false
      trigger), nod -> LISTENING < 300 ms; a false trigger with nobody speaking sends nothing
- [ ] "next" p50 < 1.2 s end of speech -> new step; progress survives 2 min airplane mode
- [ ] v1 checks: transcript within ~2 s, mic closed outside LISTENING, 8 s cap, relaunch after lock,
      permission denied, glasses vs phone mic A/B, `speakerRole` reliability
- [ ] Font coverage, brightness, 14 px diagram labels, scan inversion, double-press root exit
- [ ] **Phone screen** in the Even app's WebView: height, scrolling, safe areas, dark theme, on iOS
      and Android

## 4. v1 bring-up still open

- [ ] **Gate thresholds:** `NOT_FOUND_MIN_SIM` / `NOT_FOUND_MIN_RRF` (Part 4's live v1 eval ran with
      them unset: 0 unverified, 93.8 % answered-correct, not_found P/R 95/95 %) - Parts 4 + 5
- [ ] **`db.latency_summary()` 0 ms rows** for stages that did not run - Part 5

## 5. Done

- [x] **v2 merged into `main`:** Parts 1-5 on top of the phone-UI merge. Conflicts resolved:
      - `state.ts`/`main.ts`: Part 1's v2, with main's typed-ask/lensLink seam replayed on top
      - `Pills.tsx`: gained the `command` outcome
      - Makefile: portal/conversion targets plus `pack` and the app build; `test-ios` dropped
- [x] **Part 1's temporary v2 stubs retired:** the app runs only on Part 2's modules and mocks
      (dev utterance box, `?scenario=m1`, simulated calibration without an IMU)
- [x] **Client v2 vs Part 3's v2 relay:** pair, claim, 204, assignment, PNG diagram + cache,
      progress de-dup on the board, command fast path, 401 drops the token (12/12 e2e)
- [x] **Lost assignment re-sent** (no progress after 30 s, within the lens's 12 h TTL);
      `events.assignment_id` recorded; both verified on a live PG17 + TimescaleDB + pgvector
- [x] **"say that again"** = v1 `repeat` outside a task, `command: repeat` inside (xfail removed)
- [x] **Glyphs:** ohm sign U+2126 -> " ohm"; the app runs the relay's 32 glyph cases in place
- [x] **Port clash:** portal dev server moved to 5178 (lens v2 dev server keeps 5176)
- [x] **v2 relay (Part 3):** contract v2, auth, conversion job, every v2 route, mocks, Caddy portal
- [x] **Diagram byte format:** 8-bit grey PNG at lens levels, proven by Part 2 in the simulator;
      Part 4 renders it; it shows on the lens in the simulator from the relay
- [x] v1 sanitizer mismatch fixed; lexical OR'ed query; live v1 eval 0 unverified; VM + DNS live

## Backburner

- [ ] **Sentry trace** lens gesture -> capture -> upload -> stt -> command/answer -> render (code in
      place on both sides; needs DSNs and a hardware run)
- [ ] **Photon notifier**, **revision-fork stretch**, `/v1/sentry-tunnel`
