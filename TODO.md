# Specs TODO

Updated 2026-10-18 during v3 integration. The v2 hardware observations below are historical.
Windows: `make` = `mingw32-make`.

**Where we are:** v3 is merged into `main` and deployed from a separate VM
candidate checkout. The uploaded-source library and TODO audit are integrated into main;
redeploying this combined source and completing field acceptance remain open.
The user has no new Part 4 recordings yet and will supply them later; two wearers remain required.

- **Tests (2026-10-18, `61b9c1e`):** relay 712 passed (12 opt-in live/PG skipped), app 558 passed
  (12 skipped) + typecheck, portal 8 passed.
- **Live candidate:** VM relay `0.3.0+524beb4` on `https://getyourassto.work`, live ask path,
  Tiger DB `ok`, gate 0.68 / 0.04. The former production checkout stays at `61b9c1e` for rollback.
  App pack is now `0.4.1`; full field installation/validation is pending.
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
      Packed app version 0.4.1 from candidate `aaa266c`; artifact and SHA256 below.
- [x] Diagnostic launcher supports Python 3.11+; voice/app-loop wrappers accept `RELAY` and
      `PACE`, reject mock evidence, validate the synthetic corpus, and fail closed.
      Windows launcher/health and 22-file SAPI preparation verified. Live acceptance is in progress.
- [x] Remote deploy reads `VM_HOST` from `.env` and guards main/clean/fast-forward state.
- [x] **VM access/deployment:** existing SSH identity works; the earlier missing-key claim was
      incorrect. `/root/specs` stays on its original main checkout; `/root/specs-v3-candidate`
      serves candidate `524beb4`. Gate is 0.68 / 0.04; health confirms live ask and DB paths.
      Backed up the VM environment before changing the two gate settings; secrets remain on VM.
- [x] **Part 2:** scored, import-safe gap CLI with `--relay`, `--pace`, nonzero failure status.
- [x] **Part 1:** exact safe quota copy `Busy, try again` renders on the lens ERROR screen.
- [x] **Part 4:** recovered STT quota errors counted through `obs.record_quota_error`.
- [x] `v3-contract-app` / `v3-contract-relay` pushed and integrated into the candidate.
- [x] Production app bundles the real browser tracing SDK (previous dynamic import excluded
      it), whitelists the configured public ingest origin and filters raw audio logs. An offline
      real-SDK test creates a fresh trace per ask. Synthetic client -> VM health continued the
      same trace; Sentry ingest acknowledged HTTP 200. Glasses delivery remains a field check.
- [x] **M7 reviewed accuracy:** saved complete live responses at `7cdbbc6` score 35/36
      original answerable questions, 29/29 added loop responses and zero unverified answers.
      Approved source/wording alternatives are documented in the reviewed report; raw failures
      remain preserved. Almond milk remains a safe refusal. This is a rescore, not a new full run.
- [ ] **Clarification blocker:** focused live two-turn check at `524beb4` still safely refuses
      `How many pumps of syrup?` -> `cappuccino` (1/2 passed, zero unverified answers).
      Earlier one-off generation success did not establish route acceptance. Preserve
      `eval/results/2026-10-18-v3-syrup-524beb4.json`; investigate before claiming M9 complete.
- [ ] **M9 remaining acceptance:** 22-voice suite, live app loop, 18-question regression and
      30 paced spoken asks/quota window. Broad reruns stopped at the user's request to finish
      faster; no passing results are claimed for these. Synthetic trace evidence is recorded above.
- [ ] **Quota entitlement:** paid/higher quota has not been confirmed. The shared key is paced
      at ten seconds; observed zero 429s alone does not establish a paid account.

Merged-main validation: **867 relay passed / 13 skipped; 614 app passed / 12 skipped;
9 portal passed; app and portal typecheck/build passed**. No new hardware, paid quota or
macOS/Linux execution result is claimed.

- [x] **Canonical-domain pack:** `builds/v3/specs-0.4.1-aaa266c.ehpk` (local root checkout),
      5,070,696 bytes, SHA256 `ad23565d0c178b00f73112a69f944bed10488b14293b53632a39fa0f8e7aafd5`.
      Built with live mode, canonical origin, 50000 ms timeout and public app telemetry DSN.
      Direct ingest is whitelisted; tunnel stays off. No install on glasses claimed.
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
- [x] **Phone screen in mock mode:** health, procedures, steps, asks and deviations use
      the shared local mocks with `VITE_MOCK=1`; regression tests assert zero fetch calls.
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

- [x] **Development-bank gate calibration:** `eval/tune_gate.py` and the saved 45-question
      report are in `eval/results/2026-10-18-gate-calibration.json`. This historical v2
      calibration does not replace the deployed v3 thresholds or scoped-walkthrough checks.
- [x] **Evaluator alignment:** verified glance-only answers are valid; empty glances and
      unsupported values still fail. Historical quota-limited runs remain failure evidence.
- [x] **SOP-153 conversion recheck:** 4/4 steps, 5/5 values, 1/1 schematic and no fabricated
      values in passing steps; retained in `eval/conversion/results/2026-10-18-quota-probe/`.
- [x] **SOP upload library:** authenticated search, pagination and byte-exact original downloads
      survive failed conversions. Handoff: `docs/handoffs/SOP-CLOUD-STORAGE.md`.
- [ ] **Redeploy combined main:** library/tunnel changes need deployment and public HTTPS checks.

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

The browser SDK is pinned at 11.8.0. The DSN-pinned, bounded `/v1/sentry-tunnel` is implemented
and regression tested; deploy/configure it before enabling `VITE_SENTRY_TUNNEL`.

- [x] **Sentry browser wiring:** add/pin the official SDK 11.8.0 to the existing app lockfile;
      literal lazy import now bundles it. API export check and production bundle pass.
- [x] **`/v1/sentry-tunnel` implementation:** exact configured app DSN only, 256 KB cap,
      60 requests/min/client, unchanged binary envelope, bounded upstream timeout, no redirects;
      16 tests pass. Set VM `SENTRY_DSN_APP` to the app build DSN before enabling the tunnel.
- [ ] **Observed Sentry trace** lens gesture -> capture -> upload -> stt -> command/answer ->
      render: needs physical glasses, deployed tunnel/config and dashboard/event verification.
      No authenticated Sentry event-reading tool is connected in this session.
- [ ] **Photon notifier:** selector still intentionally supports only console. No Photon key,
      supervisor destination or account-specific server/API contract is configured; cannot verify
      a live delivery or choose among similarly named Photon products without that information.
- [ ] **Revision-fork stretch:** no zero-copy fork endpoint supplied (`DATABASE_URL_FORK` unset,
      `ENABLE_REVISION_FORK=false`). Existing explicit-revision filters work; they do not prove
      fork provisioning or isolated fork retrieval. Needs Tiger fork access/connection details.
