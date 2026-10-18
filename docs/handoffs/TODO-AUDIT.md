# TODO audit — 2026-10-18

Branch: `codex/todo-audit-completion`. Pulled the SOP branch, verified remote
`aba7001087bec9cdb6fac5bf482b4b158c6a91fa`, and merged latest main (`22bd822`).
No main/other person's branch was pushed. Original untracked work was preserved.

## Six completed technical items

1. Walkthrough citations use the published source chunk text instead of a
   paraphrased body. Missing support refuses the answer. Frozen Step unchanged.
2. All phone relay operations use the shared local mocks in `VITE_MOCK=1`.
   Tests assert no fetch, revision filtering and fresh fixture copies.
3. Official Sentry browser SDK 11.8.0 is pinned in the existing app lockfile and
   bundled by a literal lazy import; exported APIs used by the adapter are tested.
4. `/v1/sentry-tunnel` is implemented and tested: exact configured app DSN,
   bounded binary stream, per-client rate limit, timeout, no redirects or arbitrary proxying.
5. Retrieval gate calibration ran all 45 coffee QA questions with real embeddings
   and cloud Postgres: protects 36 answerable + 2 clarification questions and
   cheaply refuses 5/7 remaining cases. Local private env has the measured
   thresholds and the verified conversion model; a private backup was retained.
   No production env or billing setting was changed.
6. The independent evaluator now accepts the documented glance-only v2 answer
   shape while still rejecting unsupported numbers and empty display text.
   Six flagged questions rerun live on 3.8: 6/6 pass, 0 unverified, 3 empty bodies.

Each applicable original TODO was updated with evidence; mixed tasks were split
so an implemented piece cannot conceal an unfinished hardware/integration gate.

## Actual checks

- Final `mingw32-make test`: **715 relay passed / 13 skipped**, **557 app passed /
  12 skipped**, **9 portal passed**. Total **1,281 passed**. App typecheck/build passed.
- Portal production build passed separately.
- `SPECS_TEST_V2_DATABASE=1 ... test_db_v2_live.py`: **3 passed on Tiger**.
- Root-domain real-mode `npm run pack`: passed; `app/specs.ehpk`, SDK 0.0.16,
  minimum Even App 2.2.10, root HTTPS origin explicitly set during packing.
- Public health: 0.3.0, `ok:true`, `mock:false`, `db:ok`; portal 200. Actual root
  origin OPTIONS: 200 and matching allow-origin. Exact deployed Git SHA unknown.
- Read-only live latency: 162 events, total p50 1208 ms, p95 2806 ms; no voice
  command events. These are relay timings, not an end-to-end hardware result.
- SOP-153 real 3.8 conversion: 4/4 steps, 5/5 values, 1/1 schematic, no fabricated
  values in passing steps, one call, 18.2 s. Saved outputs/tiles are retained.
- 45-case live local-code evaluation: **not a passing quality run**. 3.5-flash-lite
  reached HTTP 429 at case 18. Its pre-alignment report is retained as historical
  failure evidence. Provider responses were not retained in that first run, so
  no retrospective claim is made that all six historical flags were false.
- Six-case live recheck: 100% correct/citation audit, but median 7148 ms exceeds
  the 3 s goal; changing the production model is not a proven latency/quota fix.
- Both QA runs used synthetic public questions and removed only their own
  analytics/session rows afterward. No production SOP was removed or published.

Reproduction from root:

```powershell
$env:PYTHONPATH = 'relay/src'
mingw32-make test
$env:SPECS_TEST_V2_DATABASE = '1'
.venv/Scripts/python.exe -m pytest relay/tests/test_db_v2_live.py -q
.venv/Scripts/python.exe eval/tune_gate.py --output eval/results/gate-calibration.json
```

For the explicit cloud pack, from `app/`:

```powershell
$env:VITE_RELAY_ORIGIN = 'https://getyourassto.work'
$env:VITE_MOCK = '0'
npm.cmd run pack
```

## Items verified still incomplete

Every unchecked TODO has a concrete dependency recorded in TODO.md:

- VM redeployment and env confirmation: SSH rejected from this computer; no
  authorized key/agent is available locally. VM and containers were not changed.
- Phone cellular reachability, exact lens CORS origin, real voice-command latency,
  IMU characterization/two-wearer M4, BLE images, mic/OS lifecycle, font/brightness
  and actual iOS/Android Even WebView checks: glasses/phones not available here.
  Existing Part 2 fixture evidence explicitly says SYNTHETIC/MISSING hardware.
- Sustained model quota: HTTP 429 reproduced; provider billing/quota/key access needed.
- Base44 sync: no tracked `ios/` currently, but that cannot prove the external
  project's sync target. No Base44 project connection/admin access is available.
- Photon: no configured API key, recipient or account-specific server contract;
  console notification remains enabled. No message was sent to anyone.
- Zero-copy revision fork: fork URL absent, flag false, no fork provisioning
  access. Existing ordinary explicit-revision tests are not fork evidence.
- Observed Sentry hardware trace: SDK/tunnel code is ready, but deployed DSN/tunnel,
  a hardware run and event visibility remain unverified. No Sentry event-reading
  MCP is connected. The applied [Sentry instrumentation skill](C:/Users/miles/.codex/plugins/cache/sentry-plugin-marketplace/sentry/1.4.5/skills/sentry-instrument/SKILL.md)
  says, "The task isn't done until the event is seen in Sentry"; therefore this
  integration checkbox remains open rather than claiming success from unit tests.

## Evidence

- `eval/results/2026-10-18-gate-calibration.json`
- `eval/results/2026-10-18-live-todo-eval.json` (pre-alignment, quota-limited)
- `eval/results/2026-10-18-glance-only-recheck.json` (six live responses)
- `eval/conversion/results/2026-10-18-quota-probe/` (live model + rendered schematic)

Work stopped after the final evaluator TODO at the user's request. No further
stretch implementation or external account changes were started.
