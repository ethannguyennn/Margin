# Margin TODO

Updated 2026-10-17 for v2 (BUILD-PLAN-V2), after Part 3's v2 relay landed on
`part-3-relay-platform` and a trial merge of Parts 1, 4 and 5 on top of it.
Windows: `make` = `mingw32-make`.

**Where we are:** Part 3's v2 relay implements every BUILD-PLAN-V2 §5 route on mocks and
on the real Part 4/5 modules. Trial merge of `part-1-lens-hands-free-ui`,
`part-4-conversion-diagrams`, `part-5-portal-data` onto it: **no conflicts; relay 650 passed,
app 418 passed, portal 8 passed; `test-ios` fails** (see §2). A real conversion ran end to end
on live Gemini through the v2 job (SOP-153: 4 steps, all verified, published, delivered as a
walkthrough). Nothing v2 is deployed yet; nothing has run on glasses.

---

## 1. Part 3 open (mine)

- [ ] **Deploy v2 to the VM** (`make deploy`): relay + Caddy image with the portal at
      `/portal/`. Add `PORTAL_TOKEN` (and `GEMINI_MODEL_CONVERT`) to the VM's `.env` first
      ([[deploy/README]]). The live relay today is the v1 build on `45-32-88-132.sslip.io`
- [ ] **Domain switch:** `MARGIN_DOMAIN=getyourassto.work, 45-32-88-132.sslip.io` on the VM so
      Caddy gets a certificate for the root domain (DNS is already correct: A -> 45.32.88.132);
      ~5 s Caddy restart. Then give Part 1 `https://getyourassto.work` for `app.json`
- [ ] **From a phone on cellular:** `https://getyourassto.work/v1/health` and `/portal/`
- [ ] **Device CORS origin:** read the `CORS rejected origin` WARN line when the glasses first call
      the relay; add that exact origin to `ALLOWED_ORIGINS`
- [ ] **`make latency`** on real traffic; report `intent='command'` rows separately (target:
      command = STT + < 50 ms, answer p50 <= 3 s)
- [ ] **Merge into main** in plan order (1, 3, 2, 4, 5). `main` already has the phone UI merged
      into `app/` (PR #3) while the v2 branches predate it: expect `app/` conflicts (Parts 1/2)
      and drop `test-ios` from the Makefile once `ios/` is gone on main

## 2. Requests to other parts (found while integrating)

- [ ] **`test-ios` / phone UI:** `Pills.tsx` has exhaustive `Record<Outcome, ...>` maps without the
      new `command` outcome, so the companion stops typechecking on contract v2. On this base it
      is `ios/src/components/Pills.tsx` (companion owner; Part 5's README: keep `test-ios` green);
      on main the same file is `app/src/phone/components/Pills.tsx` (Parts 1/2)
- [ ] **Part 5 - assignment delivery can lose a task:** `next_assignment` marks the row delivered
      before the lens has received it. If that response is lost (Wi-Fi drop), the task is never
      re-sent. Suggest: keep returning a delivered assignment until its first progress event (or
      a `delivered_at` older than ~30 s with no progress counts as undelivered)
- [ ] **Part 5 - events.assignment_id:** the plan records `context.assignment_id` on the events row.
      `/v1/ask` already passes `assignment_id=` to `write_event` when the writer accepts it; add
      the column + parameter and it flows with no Part 3 change
- [ ] **Part 5 / Part 1 - port clash:** the portal dev server (5176) and Part 1's v2 lens dev
      server (5176) use the same port
- [ ] **Part 4 - `test_ask_trust` xfail:** per BUILD-PLAN-V2 §3, "say that again" *outside a task* is
      v1 `repeat` (the relay returns `intent: repeat`); inside a task (`context.step_id`) it is
      `command: repeat`. Replace the strict-xfail `("say that again", "command")` with those two cases
- [ ] **Part 4 - model + quota:** `gemini-3.8-flash` hit the free-tier daily cap (429) during
      integration; a paid key is needed before the M3 demo. On `gemini-3.5-flash-lite` SOP-153
      converted with every value kept but **no schematic** for the star-pattern step
- [ ] **Part 1:** `U+2126` ohm sign -> `" ohm"` in `glyphs.ts` (Part 4's request)
- [ ] **Part 2:** client v2 against the mock relay: `POST /v1/devices/pair`, poll `/me` until
      claimed, `Bearer <device_token>` on every lens route, 401 -> re-pair, `204` = no task,
      `POST /v1/progress` batches up to 500 (the relay splits them for Part 5's 100 cap)

## 3. v1 bring-up still open

- [ ] **Gate thresholds:** `NOT_FOUND_MIN_SIM` / `NOT_FOUND_MIN_RRF` (Part 4's live v1 eval ran with
      them unset: 0 unverified, 93.8 % answered-correct, not_found P/R 95/95 %) - Parts 4 + 5
- [ ] **`db.latency_summary()` 0 ms rows** for stages that did not run - Part 5
- [ ] **Hardware:** transcript on the lens within ~2 s, mic closed outside LISTENING, 8 s cap,
      relaunch after lock, permission denied, glasses vs phone mic, font + brightness, root exit,
      double-nod detection, diagram legibility, BLE tile timing - Parts 1 + 2

## 4. Done

- [x] **v2 relay (Part 3):** contract v2 in `schemas.py`; v2 pipeline Protocols; `/v1/ask` command
      fast path; device + portal auth; conversion job; devices / assignments / progress /
      diagrams / materials / drafts routes; mock relay for every route (M2 demo diagram on
      SOP-114 4.2); real-mode factory for Part 4/5 v2 modules; Caddy serves the portal; Makefile
      `dev-portal`, `test-portal`, `eval-conversion`
- [x] **v1 sanitizer mismatch** fixed (Part 4: 8/8 app fixtures agree)
- [x] **Lexical leg** OR'ed query adopted in `db.py` (Part 5)
- [x] **Live v1 eval:** 0 unverified answers (Part 4, on the seeded shared database)
- [x] **VM + DNS:** `45.32.88.132`, real mode (Gemini + Tiger) live on the sslip host; the root
      domain's A record points at the VM
- [x] **Diagram byte format:** 8-bit grey PNG at lens levels, proven by Part 2; Part 4 renders it

## Backburner

- [ ] **Sentry trace** lens gesture -> capture -> upload -> stt -> command/answer -> render (code in
      place on both sides; needs DSNs and a hardware run)
- [ ] **Photon notifier**, **revision-fork stretch**, `/v1/sentry-tunnel`
