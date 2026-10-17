# Part 3 handoff

`scaffold-relay` is tagged. Merge it: `git fetch --tags && git merge scaffold-relay`.

## Contract notes (server side of `schemas.py`)

- Error codes: `stt_failed` 502, `db_down` 503, `llm_timeout` 504, `bad_request` 400.
  Relay-only addition: `internal` 500 (unexpected failure, including an over-cap
  glance/body, which raises instead of truncating). Every body has `trace_id`;
  every response also carries an `x-trace-id` header (exposed to CORS).
- A walkthrough comes back as `outcome: "answered"`, `verified: true`, one citation
  per step, `walkthrough` filled, `source` from the first step.
- An ambiguous question (`needs_clarification`) returns `not_found`, not `clarify`:
  Part 1 has no CLARIFY screen and Part 5's eval expects `not_found`.
- `/v1/deviation` accepts the ids top-level (contract) **or** nested as
  `context: {doc_id, step_id}` (what Part 2's client sends).

## Part 1

- `app.json` whitelist + `VITE_RELAY_ORIGIN`: `https://margin.<domain>` exactly,
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

## Part 5 (what the factory expects from `db.py`)

`init_pool`, `close_pool` (optional), `ping`, `get_pool()` (the psycopg pool, which
Part 4's `PgStore` queries), `list_procedures`, `write_event(**kw)`,
`next_deviation_id`, `insert_deviation(deviation_id=, session_id=, doc_id=, step_id=,
text=, notified=)`, and optionally `ingest_corpus(corpus_dir)` for `POST /v1/ingest`.
Notifiers: `notify/console.py: ConsoleNotifier()`, `notify/photon.py:
PhotonNotifier.from_settings(settings)` (or `PhotonNotifier(settings)`).
