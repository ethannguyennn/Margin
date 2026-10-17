# Quality evaluation

Run python eval/run_eval.py against a running relay. The default origin is
http://127.0.0.1:8000; use --base-url for another origin and --output for a JSON
report. There are 36 synthetic questions:

- 16 answerable lookups spanning all five procedures.
- 10 near-misses with details genuinely absent from the corpus.
- 4 ambiguous questions requiring not_found plus needs_clarification=true.
- 6 off-domain questions requiring not_found.

Every request uses text with audio=null and a fresh UUID session. The expected
revision in qa.jsonl is an assertion, not a forced retrieval revision; an
optional request_revision field is the only way to force a revision.

## Metrics

- Answered-correct rate: correct answers / all answerable questions. Correct
  requires the expected document, revision and section, all must_contain values
  in the displayed glance/body, and passing citation checks.
- not_found precision: expected refusals / all returned not_found responses.
- not_found recall: returned not_found / all questions expecting not_found.
  Clarification compliance is also checked per case and in category totals.
- Citation-verification pass rate: audited answers / all answered responses.
  Auditing requires verified=true, valid citation identity, a nonempty quote
  present in the local corpus after glyph/whitespace normalization, an approved
  default revision (or the explicit override), display caps, and supported
  numbers/units. It does not prove that arbitrary prose claims are entailed.
- Median latency: observed HTTP round-trip milliseconds, including failed
  requests. This is not hardware end-of-speech-to-lens latency.

Undefined denominators print N/A. All-refusal behavior cannot claim perfect
citation coverage. HTTP/transport failures count as failed cases. Every
response must carry a trace_id. A non-2xx answered body is still inspected for
unverified content.

Exit codes: 0 = all cases pass; 1 = quality/contract/transport failure or no
usable relay; 2 = at least one unverified answer. Fixture/mock results require
--allow-mock and are always labeled MOCK/FIXTURE ONLY, never live evidence.
The health endpoint must explicitly identify mock mode.

The independent tests use answer-key fixtures to test the harness. Their
percentages are not retrieval/generation quality numbers. As of 2026-10-17,
no live eval was possible because the relay scaffold and credentials were
unavailable. No threshold tuning or live quality metrics are claimed.
