# Specs TODO

Audited 2026-10-18 on `codex/todo-audit-completion`, incorporating current `origin/main`
and the pushed SOP-storage change `aba7001`. Checked items below have code or run evidence;
hardware/account-dependent items remain unchecked. Details: `docs/handoffs/TODO-AUDIT.md`.
Windows: `make` = `mingw32-make`.

**Where we are:** v2 is deployed (public health reports 0.3.0), and this branch adds the
remaining independently testable fixes. No glasses/hardware results are claimed.

- **Tests:** relay regression + app + portal checks pass; current counts and commands are in
  the audit handoff. App root-domain production build and `.ehpk` packing also pass.
- **Simulator, mock app:** Part 1's v2 smoke runs on Part 2's real mocks (M1, M2, returnTo,
  native exit, cold start; 25 screen assertions).
- **Simulator, live app vs. Part 3's v2 relay (`MOCK_MODE=1`):** pairing → supervisor claim →
  assignment → TASK_READY → STEP → progress on the board → relay diagram DGM-0001 rendered in
  both tiles.
- **Client v2 e2e:** 12/12 against that relay.
- **Live Postgres tests:** 3/3 rerun against the configured Tiger cloud database on 2026-10-18.
- **Not done yet:** VM redeploy/config confirmation, sustained provider quota, and the
  physical glasses/cellular/Even WebView gates below.

---

## 1. Deploy (Part 3)

- [x] **Deploy v2 to the VM:** rechecked public `/v1/health` = `ok:true, mock:false, db:ok,
      version:0.3.0`; `/portal/` = 200. The exact running Git revision is not exposed.
- [ ] **Redeploy latest code:** include current main, SOP library and this audit's fixes.
      Blocked here: SSH reaches `root@45.32.88.132` but rejects authentication; this Windows
      account has no deployment key/agent and `.env` has no key-file reference.
- [ ] **VM `PUBLIC_ORIGIN` + gate configuration:** confirm the root origin and apply calibrated
      gate settings on the VM. Last reported origin was sslip.io; cannot read/change VM env
      without SSH. Never copy private VM configuration into a frontend bundle.
- [x] **Root-domain CORS:** actual OPTIONS with `Origin: https://getyourassto.work` now returns
      200 and `Access-Control-Allow-Origin: https://getyourassto.work` (2026-10-18).
- [x] **Domain build:** built and packed with `VITE_RELAY_ORIGIN=https://getyourassto.work`,
      `VITE_MOCK=0`. The public env example now uses the root domain; whitelist already covers it.
- [ ] **From a phone on cellular:** `https://getyourassto.work/v1/health` and `/portal/`
- [ ] **Device CORS origin:** read the `CORS rejected origin` WARN line when the glasses first call
      the relay; add that exact origin to `ALLOWED_ORIGINS`
- [x] **Live latency report:** rerun against Tiger, 162 events: total p50 1208 ms, p95 2806 ms;
      unused stages excluded and commands reported separately. Relay timing excludes lens render.
- [ ] **Real voice-command latency:** still 0 command events; collect actual v2 lens traffic
      to establish STT + <50 ms relay work. Synthetic text commands cannot prove this gate.
- [x] **Live database (2026-10-17):** both migrations applied on Tiger; the demo bank (SOP-201..230 rev C,
      134 chunks) is seeded and the HX-2 rows removed (backup outside the repo:
      `db-backups/hx2-bank-2026-10-17.json`). The live v1 relay answers from it
- [x] **Opt-in live tests on Tiger:** `SPECS_TEST_V2_DATABASE=1 ... test_db_v2_live.py`:
      3 passed (migration isolation/idempotency, lost assignment redelivery, assignment event ID).

## 2. Open requests between parts

- [x] **Walkthrough citations:** quote every step's published chunk text, pinned to its revision,
      rather than its paraphrased display body. Missing source support returns ERROR. Frozen
      lens Step shape unchanged; regression tests cover paraphrases and absent source quotes.
- [x] **SOP-153 model/diagram recheck:** fresh `gemini-3.8-flash` conversion: 4/4 steps, 5/5
      values, 1/1 schematic, 0 fabricated values in passing steps; one call, 18.2 s. Evidence:
      `eval/conversion/results/2026-10-18-quota-probe/`.
- [ ] **Sustained model quota:** still not complete. The full 45-case live QA run hit HTTP 429
      on `gemini-3.5-flash-lite` from case 18. One successful conversion does not establish
      sustained quota. Requires provider quota/billing access or an available approved model/key.
- [x] **Phone mock mode:** health, procedures, steps, standalone asks and deviations now use
      Part 2's mock module with `VITE_MOCK=1`; tests assert zero fetch calls and fixture isolation.
- [ ] **Base44:** `ios/` came from a Base44 project (`ios-base-44`). If Base44 still syncs to that
      folder, point it at `app/` or stop syncing. Repo currently has no tracked `ios/`; that does
      not establish external sync settings. Needs the Base44 project owner's account/access.

## 3. Hardware (glasses + phone) - Parts 1 + 2

Protocols and the recorder are in `docs/handoffs/PART-2.md`. Open the dev server with `?dev=1`
for the IMU recorder.

All items in this section were checked for evidence and remain unverified on physical devices.
The user confirmed glasses are unavailable; simulator/unit evidence is not a hardware pass.

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

- [x] **Gate calibration:** live embeddings + Tiger for all 45 coffee QA questions, using
      `eval/tune_gate.py`: SIM `0.7389722026007067`, RRF `0.031754032258064516`; protects all 36
      answerable and 2 clarification cases, cheaply refuses 5/7 remaining cases. Applied only
      to local private env; VM rollout remains in section 1. This is development-bank calibration,
      not independent evaluation or proof of arbitrary future SOP quality.
- [x] **Evaluator contract alignment:** allow a verified glance-only answer with an empty body,
      as the v2 generator explicitly permits. Empty glances and unsupported values still fail.
      The pre-fix live report is retained; it is not presented as a passing quality run.
- [x] **`db.latency_summary()` 0 ms rows:** already excluded (`value > 0`); the report header said otherwise

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
