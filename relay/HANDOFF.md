> **v2:** the current Part 3 handoff is [docs/handoffs/PART-3.md](../docs/handoffs/PART-3.md). This file is the v1 handoff.

# Part 3 handoff

`scaffold-relay` is tagged. Merge it: `git fetch --tags && git merge scaffold-relay`.

## Contract notes (server side of `schemas.py`)

- Error codes: `stt_failed` 502, `db_down` 503, `llm_timeout` 504, `bad_request` 400.
  Relay-only addition: `internal` 500 (unexpected failure, including an over-cap
  glance/body, which raises instead of truncating). Every body has `trace_id`;
  every response also carries an `x-trace-id` header (exposed to CORS).
- A walkthrough comes back as `outcome: "answered"`, `verified: true`, one citation
  per step, `walkthrough` filled, `source` from the first step.
- An ambiguous question returns `outcome: "not_found"` (Part 1 has no CLARIFY
  screen) **plus `needs_clarification: true`**. That field is additive (default
  false) and present on every AskResponse; clients that ignore it still render
  NOT FOUND. Parts 1/2: add `needs_clarification?: boolean` to `types.ts` if useful.
- `/v1/deviation` accepts the ids top-level (contract) **or** nested as
  `context: {doc_id, step_id}` (what Part 2's client sends).

## Part 1

- `app.json` whitelist + `VITE_RELAY_ORIGIN`: `https://getyourassto.work` exactly,
  once the domain is live (deploy/README.md section 6).

## Part 2

- Mock relay: `MOCK_MODE=1 make dev-relay` on port 8080 serves the same fixture set
  (torque, walkthrough, clean, coffee, log deviation, boom -> 504 llm_timeout).
- **Sentry trace continuation needs `tracePropagationTargets: [RELAY_ORIGIN]`** in
  `obs/sentry.ts` init: the browser SDK only attaches `sentry-trace` / `baggage`
  to same-origin requests by default, so without it the relay starts a new trace.
- 5xx from the relay are retried once by the client: an `llm_timeout` (504) costs a
  second ask. Intended by the contract; just be aware.

## Part 4 (what the MOCK_MODE=0 factory loads)

| module | used as |
|---|---|
| `pipeline/intent.py` | `classify_intent(t) -> str` + `deviation_text(t)` |
| `pipeline/sanitize.py`, `verify.py` | `sanitize(text)`, `verify(draft, chunks) -> VerifyResult` |
| `pipeline/generate.py` | `gemini_client(key)`, `GeminiGenerator.from_settings(settings, client=)` |
| `pipeline/retrieve.py` | `Retriever(store, GeminiEmbedder(client, GEMINI_MODEL_EMBED, EMBED_DIM))`, `embed()`, `retrieve(q, rev, q_embedding=)`, `PgStore(pool)` |
| `pipeline/transcribe.py` | `GeminiTranscriber.from_settings(settings)` (or `GeminiTranscriber(settings)`) |

`/v1/ask` owns the gate (`best_sim < NOT_FOUND_MIN_SIM and best_rrf < NOT_FOUND_MIN_RRF`),
the one retry with the verifier's reason as `feedback=`, and the `embed` / `retrieve` /
`generate` / `verify` spans; `answer_question()` is not called. Exceptions with a
`.code` attribute keep that code.

## Part 5 (what the factory uses, as integrated on main)

- Retrieval: `Retriever(db.RetrievalStore(), embedder)`; all SQL stays in db.py
  (Part 4's `PgStore` is not used).
- Walkthrough branch of `/v1/ask`: `walkthrough.build_walkthrough(doc_id, revision)`;
  `LookupError` -> not_found, `ValueError` (over-cap step) -> 500 internal.
- `/v1/deviation` and the deviation branch: `walkthrough.log_deviation(session_id,
  text, doc_id, step_id, notifier=)` -- row committed before notifying;
  `ValueError` -> 400 bad_request. Lens copy says "Supervisor alert sent", never
  that a human received it.
- `GET /v1/procedures/{doc_id}/steps`: `db.steps_for`. Lifespan: `db.init_pool()` /
  `db.close_pool()`. Health: `db.ping()`. Events: `db.write_event(...)`.
- Notifier: `notify.get_notifier(settings)` (console only until Photon is verified).
- `make latency` -> `db.latency_summary()`; `make eval` passes `--base-url` (8080).
- PyYAML is a runtime dependency; the image is an editable install at /srv/specs so
  `db.ingest_corpus()` finds `db/seed.py` and `corpus/`.
- Open: `latency_summary()` includes 0 ms rows for stages that did not run (stt on
  text asks, generate on gated not_found), which pulls those p50s down.
