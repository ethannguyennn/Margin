# Specs TODO

Updated 2026-10-18 during v3 integration. The v2 hardware observations below are historical.
Windows: `make` = `mingw32-make`.

**Where we are:** v3 is staged on `codex/v3-integration` and deployed from a separate VM
candidate checkout. `main` and the four part branches are retained until acceptance is complete.
The user has no new Part 4 recordings yet and will supply them later; two wearers remain required.

- **Tests (2026-10-18, `61b9c1e`):** relay 712 passed (12 opt-in live/PG skipped), app 558 passed
  (12 skipped) + typecheck, portal 8 passed.
- **Live candidate:** VM relay `0.3.0+155d899` on `https://getyourassto.work`, live ask path,
  Tiger DB `ok`, gate 0.68 / 0.04. The former production checkout stays at `61b9c1e` for rollback.
  App pack is now `0.4.0`; full field installation/validation is pending.
- **Real glasses (`61b9c1e`):** double nods work (the G2 IMU is a gravity-normalised
  accelerometer), long press = nod, baked PNG reference images render on the lens (the host only
  renders encoded images, never raw Gray8), natural voice commands ("go to the next step").
- **Not yet on glasses:** the v2 task flow. The relay log shows real `/v1/ask` and
  `/v1/procedures` traffic, but no `/v1/devices/*`, `/v1/assignments/*`, `/v1/progress` or
  `/v1/diagrams/*` calls.

---

## 1. Deploy and live checks (Part 3)

**v3 platform checkpoint (2026-10-18, Part 3 taken over by Codex):**

- [x] Health distinguishes ask mocks from conversion mocks; verbose health adds gate,
      commit and process-lifetime Gemini 429 counters. Normal response keeps its four fields.
- [x] Provider quota failures return safe `Busy, try again` copy through the shared error
      helper; the API client suppresses its extra 5xx retry. Frozen error codes unchanged.
- [x] Container probe rejects `ok: false`, even with HTTP 200.
- [x] `make eval-conversion` now uses `--strict`; `sync-branches` lists all four v3 branches.
- [x] App example origin is `https://getyourassto.work`; timeout remains 50000 ms.
      Client validates clarify/scope and passes verified graphic IDs. Contract tags are integrated.
      Packed app version 0.4.0 from candidate `22c5468`; artifact and SHA256 below.
- [x] Diagnostic launcher supports Python 3.11+; voice/app-loop wrappers accept `RELAY` and
      `PACE`, reject mock evidence, validate the synthetic corpus, and fail closed.
      Windows launcher/health and 22-file SAPI preparation verified. Live acceptance is in progress.
- [x] Remote deploy reads `VM_HOST` from `.env` and guards main/clean/fast-forward state.
- [x] **VM access/deployment:** existing SSH identity works; the earlier missing-key claim was
      incorrect. `/root/specs` stays on its original main checkout; `/root/specs-v3-candidate`
      serves candidate `155d899`. Gate is 0.68 / 0.04; health confirms live ask and DB paths.
      Backed up the VM environment before changing the two gate settings; secrets remain on VM.
- [x] **Part 2:** scored, import-safe gap CLI with `--relay`, `--pace`, nonzero failure status.
- [x] **Part 1:** exact safe quota copy `Busy, try again` renders on the lens ERROR screen.
- [x] **Part 4:** recovered STT quota errors counted through `obs.record_quota_error`.
- [x] `v3-contract-app` / `v3-contract-relay` pushed and integrated into the candidate.
- [ ] **M7/M9 live acceptance:** gap, full eval, voice, app loop, 18-question regression,
      30 paced asks, latency and trace evidence. Preserve failed runs as well as passing reports.
- [ ] **Quota entitlement:** paid/higher quota has not been confirmed. The shared key is paced
      at ten seconds; observed zero 429s alone does not establish a paid account.

Integration validation: **810 relay passed / 12 skipped; 609 app passed / 12 skipped;
8 portal passed; app and portal typecheck/build passed**. Subsequent harness-only regression:
25 tests passed. No new hardware, paid quota or macOS/Linux execution result is claimed.

- [x] **Canonical-domain pack:** `builds/v3/specs-0.4.0-22c5468.ehpk` (local root checkout),
      4,928,949 bytes, SHA256 `1952ab1bc07415d0d8f212e102f4637c66faa70c0e5b52e6be407a0ecbb46dc2`.
      Built with live mode, canonical origin and 50000 ms timeout. No install on glasses claimed.
- [ ] **From a phone on cellular:** `https://getyourassto.work/v1/health` and `/portal/`
- [ ] **`make latency` on real v2 traffic:** prints all events, answers and `intent='command'`
      separately. Live DB 2026-10-18: relay p50 total 1208 ms, p95 2850 ms (159 events);
      **0 command events yet** (target: command = STT + < 50 ms, answer p50 <= 3 s)
- [ ] **Opt-in live tests on Tiger** (`SPECS_TEST_V2_DATABASE=1`, `DATABASE_URL`). They write to
      the shared database; run them deliberately - Part 5

## 2. Open requests between parts

- [x] **Trust: walkthrough citations** now use the stored raw source text through
      `Step.source_text`; authored display bodies cannot serve as citation quotes. Regression tested.
- [ ] **Gemini paid key before the M3 demo:** the key is free tier (`gemini-3.8-flash`: 20
      requests/day; `gemini-3.5-flash-lite`: 15/min). Conversion is about 2-3 calls per material.
      On `gemini-3.5-flash-lite`, SOP-153 converted every value but **no schematic**. Re-run
      `make eval-conversion` on the model we demo with - Part 4 + account owner
- [x] **`make eval-conversion` fails closed:** target now passes `--strict`, so missing steps,
      values or expected diagrams fail alongside fabrication - Part 3 v3 checkpoint
- [ ] **Head shake is impossible on this IMU:** an accelerometer cannot see yaw, so "shake: back"
      became "double: back" (`61b9c1e`). Update BUILD-PLAN-V2 section 3 (gestures table) and the M4
      criteria, which still describe a shake - Parts 1 + 2
- [ ] **Phone screen in mock mode:** with `VITE_MOCK=1` the lens uses Part 2's mocks, but the phone
      screen's procedures/steps/deviation calls still go to the relay. Run a `MOCK_MODE=1` relay
      alongside - Parts 2 + 3
- [ ] **Base44:** `ios/` is gone from the repo, but the `ios-base-44` remote branch remains. Confirm
      Base44 no longer syncs into this repo (or it may recreate `ios/`), then delete that branch -
      owner of PR #1

## 3. Hardware (glasses + phone) - Parts 1 + 2

Protocols and the recorder are in `docs/handoffs/PART-2.md`. Open the dev server with `?dev=1`
for the IMU recorder.

- [ ] **v2 task flow on glasses (M3):** pair code on the lens -> claim in the portal -> assign a
      published SOP -> TASK_READY -> step through by voice -> progress on the board -> "show
      diagram". None of these routes has seen real glasses traffic yet
- [ ] **Device CORS origin on the v2 flow:** 6 h of real-glasses `/v1/ask` traffic logged **0** CORS
      rejections, so the host's origin is accepted. Re-check the log once the pairing routes run
- [ ] **IMU characterisation (remaining):** axes/units are settled (gravity-normalised
      accelerometer, tilt from rest posture). Still open: samples/s per pace code
      (P100/P500/P1000; the app now measures it at runtime), and recorded fixtures from real
      wearers (still, double nods, bench work, walking, talking) committed for the detector tests
- [ ] **Two-tile DIAGRAM screen on the lens** + BLE time per tile. Single baked PNG references
      render on glasses; relay diagram tiles (Part 4's four real tiles in
      `eval/conversion/results/2026-10-17-gemini-3.8-flash/tiles/`) are untested on hardware
- [ ] **M4, two wearers:** 20 double nods each (>= 95 %), 30 min bench work each (<= 1 false
      trigger), nod -> LISTENING < 300 ms; a false trigger with nobody speaking sends nothing.
      Back is double-tap, not shake
- [ ] "next" p50 < 1.2 s end of speech -> new step; progress survives 2 min airplane mode
- [ ] v1 checks: transcript within ~2 s, mic closed outside LISTENING, 8 s cap, relaunch after lock,
      permission denied, glasses vs phone mic A/B, `speakerRole` reliability
- [ ] Font coverage, brightness, 14 px diagram labels, scan inversion, double-press root exit
- [ ] **Phone screen** in the Even app's WebView: height, scrolling, safe areas, dark theme, on iOS
      and Android

## 4. v1 bring-up still open

- [x] **Gate thresholds:** VM now uses `NOT_FOUND_MIN_SIM=0.68`, `NOT_FOUND_MIN_RRF=0.04`;
      verbose health exposes both. Full live quality evaluation remains part of M7/M9 above.

## 5. Done

- [x] **First real-glasses run (`61b9c1e`, 2026-10-18):** nod detection from the accelerometer,
      long press as a nod fallback, baked PNG lens references, text drawn before the picture with a
      text-only fallback, natural voice commands (0 of the 45 eval questions reclassified)
- [x] **v2 deployed (2026-10-18):** VM at `61b9c1e`, relay `0.3.0`; `PORTAL_TOKEN` and
      `GEMINI_MODEL_CONVERT=gemini-3.8-flash` set; `.env` backed up to
      `/root/specs/.env.bak-2026-10-18`
- [x] **VM origins:** `PUBLIC_ORIGIN=https://getyourassto.work`; `ALLOWED_ORIGINS` = root domain,
      sslip.io, `http://localhost:5174`; root-domain preflight 200, unknown origins refused
- [x] **`make latency`** runs on Windows (selector event loop) and reports commands apart from
      answers; `db.latency_summary()` already excludes stages that did not run
- [x] **Live database (2026-10-17):** both migrations applied on Tiger; the demo bank (SOP-201..230
      rev C, 134 chunks) is seeded and the HX-2 rows removed (backup outside the repo:
      `db-backups/hx2-bank-2026-10-17.json`)
- [x] **v2 merged into `main`:** Parts 1-5 on top of the phone-UI merge (`state.ts`/`main.ts`,
      `Pills.tsx`, Makefile conflicts resolved); `ios/` later removed
- [x] **Part 1's temporary v2 stubs retired:** the app runs only on Part 2's modules and mocks
      (dev utterance box, `?scenario=m1`, simulated calibration without an IMU)
- [x] **Client v2 vs Part 3's v2 relay:** pair, claim, 204, assignment, PNG diagram + cache,
      progress de-dup on the board, command fast path, 401 drops the token (12/12 e2e)
- [x] **Lost assignment re-sent** (no progress after 30 s, within the lens's 12 h TTL);
      `events.assignment_id` recorded; both verified on a live PG17 + TimescaleDB + pgvector
- [x] **"say that again"** = v1 `repeat` outside a task, `command: repeat` inside
- [x] **Glyphs:** ohm sign U+2126 -> " ohm"; the app runs the relay's 32 glyph cases in place
- [x] **Port clash:** portal dev server moved to 5178 (lens v2 dev server keeps 5176)
- [x] **v2 relay (Part 3):** contract v2, auth, conversion job, every v2 route, mocks, Caddy portal
- [x] **Diagram byte format:** 8-bit grey PNG at lens levels; proven in the simulator by Part 2 and
      confirmed on hardware (the host only renders encoded images)
- [x] v1 sanitizer mismatch fixed; lexical OR'ed query; live v1 eval 0 unverified; VM + DNS live

## Backburner

- [ ] **Sentry trace** lens gesture -> capture -> upload -> stt -> command/answer -> render (code in
      place on both sides; needs DSNs and a hardware run)
- [ ] **Photon notifier**, **revision-fork stretch**, `/v1/sentry-tunnel`
