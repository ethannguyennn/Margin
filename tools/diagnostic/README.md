# Live worker-loop diagnostic

The checks behind the 2026-10-18 full-loop diagnostic. They run the real relay against the live
Tiger DB and Gemini (from the root `.env`), with real speech (Windows SAPI) and the app's real
Detector, LensController, renderer and API client. Speech is synthetic, not a recording of a
worker. Live calls consume the shared Gemini quota. Pacing reduces bursts; one ask can make
multiple calls, so `PACE=10` does not guarantee staying inside the free-tier quota.

## One-command entry points (v3 Part 3)

Install dependencies with `make install` first. On Windows, use `mingw32-make` in place of
`make`. Python 3.11+ is supported; the local launcher selects the Windows Selector event loop
needed by psycopg. Commands run from the repository root:

```sh
make diag-relay                                      # local relay on 127.0.0.1:8090
make diag-voice RELAY=https://getyourassto.work PACE=10
make diag-loop RELAY=https://getyourassto.work PACE=10
make diag-gap RELAY=https://getyourassto.work PACE=10
```

`diag-relay` only launches a local HTTP server; override its local port with
`RELAY=http://127.0.0.1:8091`. Start it in a separate terminal. The other targets accept a
local or remote HTTP(S) origin. They refuse mock asks, an unhealthy relay, or a non-live DB.
`PACE` is seconds between requests; announce long runs before using the shared key.

`diag-voice` prepares the 22 utterances, generates Windows SAPI WAVs, validates every WAV's
16 kHz/16-bit/mono PCM format, runs the voice suite against `RELAY`, and checks that every
expected result exists and passes. Failures, missing results and exceptions exit nonzero.
`diag-loop` prepares the same speech, copies Part 1's test into `app/tests/`, runs installed
Vitest with the target and pacing environment, then removes its copy even if the test fails.
An existing test copy is preserved and causes an error.

On **macOS/Linux**, copy the synthetic `tools/diagnostic/wav/` directory prepared on Windows
from the exact same `voice_loop.py` revision before running either voice target. Automatic
speech synthesis is Windows-only. The wrapper validates the copied corpus before making asks.
Only synthetic audio belongs in this directory. Generated speech and results remain ignored.

`diag-gap` invokes Part 2's scored CLI with `--relay` and `--pace`; integrate the Part 2 branch
before running it. The wrapper rejects the old unscored script. `diag-loop` always enables
the v3 clarify/scope test as well as the voice loop; a skipped v3 test is not passing evidence.

Validation on Windows: mock launcher and verbose health passed; SAPI produced and validated
22 files; wrapper tests cover incomplete/failed evidence and cleanup after a failing app test.
Live voice/app-loop runs and macOS/Linux execution have **not** been validated in this checkpoint.

## Original individual probes

Run everything from the repo root on Windows (Git Bash or PowerShell).

| Step | Command | Checks |
|---|---|---|
| 1. Relay | `.venv/Scripts/python.exe tools/diagnostic/run_relay.py` | current code on `127.0.0.1:8090` (psycopg needs the SelectorEventLoop that uvicorn's CLI does not pick on Windows). In a worktree, run it from the worktree root with a copy of `.env` |
| 2. Speech | `cd tools/diagnostic && ../../.venv/Scripts/python.exe voice_loop.py prepare && powershell -File tts.ps1` | writes `utterances.txt` and `wav/<n>.wav` (16 kHz s16le mono) |
| 3. Voice loop | `../../.venv/Scripts/python.exe voice_loop.py run 6` | 10 SOP-opening prompts, 6 navigation commands, 6 clarifying questions on SOP-210 steps, by voice; writes `results.json` |
| 4. Clarifying rate | `../../.venv/Scripts/python.exe clarify_rate.py` | the 6 clarifying questions x 3, as text, scored as the lens would show them |
| 5. Gap probe | `../../.venv/Scripts/python.exe gap_probe.py` | natural opens, walkthrough scope, ambiguity, chained follow-ups, picture questions |
| 6. Gate scores | `PYTHONPATH=relay/src .venv/Scripts/python.exe tools/diagnostic/gate_scores.py` (repo root) | `best_sim`/`best_rrf` for the 45 eval questions + walkthrough prompts; re-measure after any embedding or corpus change |
| 7. App loop | copy `loop.test.ts` to `app/tests/zz-diagnostic-loop.test.ts`, then in `app/`: `SPECS_DIAG_RELAY=http://127.0.0.1:8090 npx vitest run tests/zz-diagnostic-loop.test.ts --disableConsoleIntercept`; delete the copy afterwards | IMU double nod -> mic -> speech -> walkthrough -> voice/swipe stepping -> clarifying questions -> images on every illustrated step -> TASK_DONE, 0 false nods during bench work |

Part 2's current `clarify_rate.py --relay URL --pace 10 --output PATH` independently checks
18 answers and their citations, accepting verified glance-only answers. Generated files (`wav/`, `utterances.txt`, `results.json`,
`gate_scores.json`, logs) are git-ignored.
