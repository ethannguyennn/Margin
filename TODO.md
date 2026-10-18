# Margin TODO

Updated 2026-10-17 from all READMEs, handoffs and a full test run of the integrated
branch; revised after the iPhone companion (`ios/`) was merged into the Even Hub app.
Windows: `make` = `mingw32-make`.

## 0. New since the first version

- [x] **One Even Hub app.** The `ios/` companion now lives in `app/src/phone` as the phone
      screen the Even app shows in its WebView; `main.ts` still draws the lens through the
      SDK. Typed questions on the phone are answered on the glasses too, every lens answer
      (spoken or typed) shows in full on the phone, push-to-talk and the mic toggle drive the
      real lens. Verified in the official simulator (glasses + webview screenshots, 0 errors).
      `ios/` is gone; branch `merge-phone-ui` - needs review by Parts 1 + 2 before main
- [x] **Phone -> lens delivery** solved by the merge (same app, same session; no relay route)
- [ ] **Check the phone screen on real hardware:** the Even app's WebView height, scrolling,
      safe areas and dark theme, on iOS and Android - Parts 1 + 2
- [ ] **Base44:** `ios/` came from a Base44 project (`ios-base-44`). If Base44 still syncs to
      that folder, point it at `app/` or stop syncing, or it may recreate `ios/` - owner of PR #1
- [ ] **Re-merge into main** once `merge-phone-ui` is approved (it already contains
      `part-3-relay-infra`) - Part 3
- [ ] **Mock mode:** with `VITE_MOCK=1` the lens uses Part 2's fixtures, but the phone's
      procedures/steps/deviation calls still go to the relay, so run a `MOCK_MODE=1` relay
      alongside - Parts 2 + 3

**Where we are:** all five parts are merged and run end to end on mocks, and the live
relay on the VM runs real Gemini + Tiger (`mock: false`). `make test` is green (relay 343
passed, app 237 passed + typecheck + production build). The packed `.ehpk` is 138 KB.
**Not yet tested on the glasses.**

---

## 1. Accounts and secrets (blocking, needs you)

- [x] **Domain:** `getyourassto.work` (Porkbun); the relay lives at `https://getyourassto.work`
- [x] **Vultr VM:** `45.32.88.132` (`ssh margin-vm` once this laptop's key is authorized)
- [ ] **Authorize this laptop's key** (`margin-deploy@enguy-laptop`) in `/root/.ssh/authorized_keys` on the VM
- [ ] **DNS (Porkbun):** delete the `pixie.porkbun.com` ALIAS + `*` CNAME, add A (blank host) -> `45.32.88.132` ([[deploy/README]])
- [ ] **Gemini API key** -> `.env`: `GEMINI_API_KEY`, `GEMINI_MODEL_GENERATE=gemini-3.5-flash-lite`,
      `GEMINI_MODEL_TRANSCRIBE=gemini-3.5-flash-lite`, `GEMINI_MODEL_EMBED=gemini-embedding-2`, `EMBED_DIM=768`
- [ ] **Tiger Cloud service** -> `DATABASE_URL`
- [ ] `ADMIN_TOKEN` (any long random string), `MARGIN_DOMAIN`, `ACME_EMAIL`, `PUBLIC_ORIGIN`

## 2. Bring-up, in order

- [ ] **Probe the DB:** `python db/seed.py --probe-only` (vector + HNSW + hypertable) - Part 5
- [ ] **Seed twice:** `make seed`, twice; both runs report 59 chunks / 35 steps, no duplicates - Part 5
- [ ] **Relay in real mode:** `MOCK_MODE=0 make dev-relay`; `make health` shows `"mock": false, "db": "ok"`
- [ ] **Eval:** `make eval`; record the four metrics; **0 unverified answers** - Parts 4 + 5
- [ ] **Tune the gate:** `NOT_FOUND_MIN_SIM` / `NOT_FOUND_MIN_RRF` with `retrieve.tune_gate` on the 10 near-misses, put them in `.env`, re-run `make eval` - Parts 4 + 5
- [ ] **Deploy:** `make deploy` on the VM; `https://getyourassto.work/v1/health` answers **from a phone on cellular** - Part 3
- [ ] **Whitelist:** replace `https://margin.example.com` in `app/app.json` and set `VITE_RELAY_ORIGIN` to the exact origin, then `npm run pack` - Part 1
- [ ] **Device origin:** sideload, press once, read the `CORS rejected origin` line in `make logs`, add it to `ALLOWED_ORIGINS`, redeploy; the preflight must be 2xx - Part 3
- [ ] **Latency:** `make latency`; relay p50 total well under 3 s - Part 3

## 3. Hardware checks (glasses + phone)

- [ ] Speaking a sentence puts the right transcript on the lens within ~2 s (M3) - Part 2
- [ ] Mic closed outside LISTENING; 8 s cap (a 20 s press sends 8 s) - Part 2
- [ ] Phone locked 5 min, relaunched: the next press still captures - Part 2
- [ ] Mic permission denied: clear message, no crash, no retry loop - Part 2
- [ ] Glasses mic vs phone mic A/B - Part 2
- [ ] Font coverage + brightness on the real lens; double-press exit at root - Part 1

## 4. Bugs and mismatches found (needs owner)

- [ ] **Sanitizers disagree** (`app/tests/sanitize-fixtures.json` vs relay `sanitize.py`, 6/8 agree) - Parts 1 + 4
  - `10Ω` (U+03A9): app -> `10 ohm`, relay -> `10`. A resistance spec loses its unit on the lens.
  - Control characters `\x00` / `\x7f`: app drops them, relay keeps them.
  - Agree on one fixture list and copy it verbatim into both suites (Part 4 acceptance item).
- [ ] **Lexical leg:** the relay now retrieves through `db.RetrievalStore` (`websearch_to_tsquery`, every term ANDed). Part 4 found spoken questions rarely match ANDed terms and wrote an OR'ed query for `PgStore`. Pick one in `db.py` before tuning the thresholds - Parts 4 + 5
- [ ] **`db.latency_summary()` counts 0 ms rows** for stages that did not run (stt on text asks, generate on gated not_found), which drags those p50s down. Filter `value > 0` and/or by outcome - Part 5
- [ ] **Optional:** add `needs_clarification?: boolean` to `app/src/types.ts` (the relay now sends it) - Parts 1 + 2

## 5. Done

- [x] Relay: contract, CORS, trace ids, mocks, real-mode factory, routes, Makefile, deploy files - Part 3
- [x] Real mode wired to Part 5: `RetrievalStore`, `build_walkthrough`, deviation row saved before notifying, `needs_clarification`, `make latency` via `db.latency_summary`, PyYAML runtime, image ingest path - Part 3
- [x] Lens UI state machine, pagination, glyphs, persistence, simulator evidence, `.ehpk` packs - Part 1
- [x] Client (timeout/abort/one retry), PCM capture, mock fixtures, contract e2e test - Part 2
- [x] Intent, hybrid retrieval + RRF + gate, structured generation, citation verifier, transcriber - Part 4
- [x] Synthetic corpus (6 files), migration, seed, `db.py`, walkthrough/deviation, 36-question eval - Part 5
- [x] Phone screen (Answer / Lens / SOPs, from the `ios/` companion, PR #1) merged into the Even Hub app

## Backburner (not needed to get the app working)

- [ ] **Sentry:** `SENTRY_DSN_RELAY` / `VITE_SENTRY_DSN`, confirm the relay span tree under the app's trace in Sentry, optional `/v1/sentry-tunnel`. The code is in place and Sentry stays off with no DSN.
- [ ] **Photon notifier** (SMS/iMessage); console notifier is enough for the demo - Part 5
- [ ] **Revision fork stretch:** SOP-114 rev D on a Tiger fork, `DATABASE_URL_FORK`, "Changed in rev D" - Parts 4 + 5
