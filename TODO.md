# Margin TODO

Updated 2026-10-17 from all READMEs, handoffs and a full test run of the integrated
branch; revised after PR #1 (iPhone companion, `ios/`) merged into main.
Windows: `make` = `mingw32-make`.

## 0. New since the first version

- [ ] **Re-merge `part-3-relay-infra` into main.** PR #1 merged on top of the older main, so
      main is missing the real-mode fixes (`25cd8a8`) and this file. main is already merged
      into this branch, so a PR `part-3-relay-infra -> main` is a fast-forward - Part 3
- [x] **CORS for the iPhone companion, local + LAN:** recommended `ALLOWED_ORIGINS` and
      `ALLOWED_ORIGIN_REGEX` (lens 5174 + companion 5175, 192.168.x / 10.x) are in
      `.env.example` and covered by `test_cors.py`. Copy them into your `.env` - Part 3
- [ ] **CORS, Base44 preview origin:** open the preview against the relay, read the
      `CORS rejected origin` log line, add that exact origin to `ALLOWED_ORIGINS` - Part 3
- [ ] **iPhone over HTTPS needs the HTTPS relay:** a page served over https (Base44 preview,
      home-screen shortcut) cannot call an `http://` relay (mixed content), so this depends on
      the deploy in section 2 - Part 3
- [x] **`ios/` in `make test`:** `make test-ios` typechecks and builds the companion; `make
      install` also runs `npm ci` in `app/` and `ios/`; `make dev-ios` serves it on :5175 - Part 3
- [ ] **`ios/` unit tests** (none yet; a client test like `app/tests/client.test.ts`) - ios owner
- [ ] **Decide:** phone -> lens delivery. The relay is request/response only, so the companion
      cannot push to the glasses or read the lens session. Needs a new relay route (e.g. a
      session read endpoint) if we want it for the demo - Part 3 + ios owner

**Where we are:** all five parts are merged and run end to end on mocks.
`make test` is green (relay 343 passed, app 202 passed, ios typecheck + build). The app's real client passes
its contract test against the real relay. Real mode wires every real module with zero
mocks, but **nothing has run against Gemini, Tiger Cloud, the domain or the glasses yet.**

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
- [x] iPhone companion web app (`ios/`): Answer / Lens / SOPs screens on the same contract, merged as PR #1

## Backburner (not needed to get the app working)

- [ ] **Sentry:** `SENTRY_DSN_RELAY` / `VITE_SENTRY_DSN`, confirm the relay span tree under the app's trace in Sentry, optional `/v1/sentry-tunnel`. The code is in place and Sentry stays off with no DSN.
- [ ] **Photon notifier** (SMS/iMessage); console notifier is enough for the demo - Part 5
- [ ] **Revision fork stretch:** SOP-114 rev D on a Tiger fork, `DATABASE_URL_FORK`, "Changed in rev D" - Parts 4 + 5
