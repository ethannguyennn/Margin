# Part 3 v3 — Platform, deploy & integration

**Branch:** `v3-part-3-platform-deploy` (from tag `v3-base`)
**Owner:** _____
**Read first:** `BUILD-PLAN-V3.md` (§1 where the loop stands, §3 milestones, §4 merge protocol).
**Owns:** getting the code that works locally onto the VM and the glasses, keeping it within
the Gemini quota, making the live diagnostic one command, and integrating the four branches.
**Milestones:** M6 (VM redeployed with `v3-base` + gate), M9 (everything deployed and verified
by voice against the VM). You are also the merge coordinator for `main`.

---

## 0. Setup

```bash
git fetch && git switch v3-part-3-platform-deploy
make install && make test            # relay 740, app 560 + tsc, portal 8 on v3-base
make health URL=https://getyourassto.work
```

VM access (`VM_HOST` in `.env`) and the Gemini account are needed for §4.1-4.3. Never paste
keys into the channel, the vault or a commit.

## 1. Files you own

```
deploy/**, Makefile, .env.example, app/.env.example, TODO.md
relay/src/specs_relay/{main.py,config.py,obs.py,latency.py,auth.py,jobs.py}
relay/src/specs_relay/routes/{health.py,devices.py,assignments.py,progress.py,diagrams.py,
                              materials.py,drafts.py,ingest.py,deviation.py}
app/src/api/client.ts, app/src/settings.ts, app/src/obs/sentry.ts, app/app.json, app/package.json
tools/diagnostic/{run_relay.py,README.md,tts.ps1}       # loop.test.ts belongs to Part 1; you wrap it in make
portal/**                                              # the supervisor portal (claim, assign, board)
relay/tests/test_{boot,cors,auth,obs,latency,routes_v2,jobs,data_routes}.py, app/tests/client.test.ts,
app/tests/integration.test.ts, app/tests/relay.e2e.test.ts
```

## 2. Files you must NOT touch

`routes/ask.py`, `pipeline/*` except as agreed, `schemas.py`, `eval/**` (Part 2);
`app/src/state.ts`, `app/src/ui/**`, `app/src/phone/**`, `app/src/types.ts` (Part 1);
`app/src/motion/**`, `app/src/audio/**`, `pipeline/transcribe.py` (Part 4).

## 3. The work

### 3.1 Redeploy today's code (day 1, M6)

**Evidence:** the VM runs `61b9c1e` (TODO.md header). None of the 2026-10-18 loop fixes are
live: empty-body answers, step-context follow-ups, scoped starts, dropped uncited pictures, STT
retry, natural opening phrases. The gate is unset on the VM ("retrieval gate disabled").

**Do:**
1. PR `v3-base` (or `demo-deploy-fixes`) -> `main`; merge when `make test` is green.
2. On the VM `.env`: `NOT_FOUND_MIN_SIM=0.68`, `NOT_FOUND_MIN_RRF=0.04` (measured; see
   `.env.example` for the numbers and `tools/diagnostic/gate_scores.py` to re-measure).
3. `make deploy-remote`, then `make health URL=https://getyourassto.work` and check the relay
   log no longer says "retrieval gate disabled".
4. Repeat for every PR that lands in `main` during v3 (M7, M8).

### 3.2 Gemini quota (blocker for any demo)

**Evidence:** the key is free tier: `gemini-3.5-flash-lite` 15 req/min, shared by STT and
generation. About 15 quick asks exhausted it and every ask after that failed. One ask costs 1
STT + 1-2 generations + 1 embedding.

**Do:**
1. Account owner: a paid key (or a project with higher RPM) before M9; put it only in the VM
   and local `.env`. Note the new limits in `.env.example`.
2. Until then and as a safety net: log 429s with a counter in `obs.py` and expose
   `gemini_429_total` on `/v1/health` (verbose) so a demo can see quota trouble coming.
3. Lens copy for quota failures: `client.ts` maps the relay's error to the lens; make sure a
   quota failure says "Busy, try again" rather than a generic error (coordinate the string with
   Part 1).

### 3.3 Health tells the truth

**Evidence:** `/v1/health` reports `"mock": true` whenever any pipeline piece is mocked, and
`GEMINI_MODEL_CONVERT` is unset, so convert is mocked. A fully live ask path therefore reports
mock, and `eval/run_eval.py` refuses to produce live evidence.

**Do:** report `mock` for the ask path (transcriber, retriever, generator, db) separately from
conversion (`mocked: [...]` already lists them), or set `GEMINI_MODEL_CONVERT` on the VM and
locally. Test in `test_boot.py`. Part 2's eval must run on a live relay without `--allow-mock`.

### 3.4 App build and pack for the glasses

**Evidence:** `app/.env.example` and the last pack point at `https://45-32-88-132.sslip.io`.

**Do:** pack with `VITE_RELAY_ORIGIN=https://getyourassto.work` (already whitelisted in
`app.json`), `VITE_ASK_TIMEOUT_MS=50000`, bump `app.json` version per pack, `make pack`, and
hand Part 4 the `.ehpk` with its commit hash. Validate the v3 fields (`clarify`, `scope`) in
`client.ts` once Part 1 tags `v3-contract-app`: drop malformed ones, never crash; tests in
`client.test.ts`.

### 3.5 The diagnostic as one command

**Evidence:** today the live checks are seven manual steps (`tools/diagnostic/README.md`).

**Do:** `make diag-relay` (starts `run_relay.py`), `make diag-voice` (prepare + tts + voice loop),
`make diag-gap`, `make diag-loop` (copies `loop.test.ts`, runs it, removes the copy), each
taking `RELAY=` so they can target the VM (`RELAY=https://getyourassto.work`). Exit non-zero
when a check fails. Pace via `PACE=`. Windows and macOS/Linux both work (`tts.ps1` is
Windows-only; document the fallback: pre-recorded `wav/` from a Windows machine).

### 3.6 Latency and traces

`make latency` on real v2/v3 traffic: answer p50 <= 3 s, command (`intent='command'`) = STT +
< 50 ms. Sentry DSNs in the VM `.env`; one trace per ask (TODO backburner). Report the numbers
in `TODO.md` after M9.

### 3.7 Integration (you own `main`)

- Update `Makefile` `BRANCHES` (`sync-branches`) to the four v3 branches.
- Merge in the order 3, 2, 1, 4 (BUILD-PLAN-V3 §4). Before each merge: `make test` on the
  merge result, then `make diag-gap RELAY=<local>`; after deploy, `make diag-voice` against
  the VM.
- Keep `TODO.md` current: move done items, add what Part 4 finds on glasses.

## 4. Build order

3.1 (day 1) -> 3.3 -> 3.2 -> 3.5 -> 3.4 (when Part 1 tags) -> 3.6 -> 3.7 throughout.

## 5. Acceptance (M9)

- The VM serves `main` at M8's commit; `/v1/health` is `ok`, not mock for the ask path, `db: ok`;
  the relay log shows the gate thresholds.
- `make diag-voice RELAY=https://getyourassto.work` and `make diag-gap RELAY=...` pass.
- A packed `.ehpk` pointing at `https://getyourassto.work` is in Part 4's hands with its hash.
- 30 asks at a worker's pace (one per 10 s) against the VM: 0 quota errors.
- `make test` green on `main`; `TODO.md` updated.

## 6. House rules

Every rule in BUILD-PLAN-V3 §5. Keys live only in `.env` files on the VM and your machine.
Destructive VM operations (compose down, `.env` edits) are announced in the channel first.
No `Co-Authored-By: Claude` in commits.
