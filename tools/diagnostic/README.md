# Live worker-loop diagnostic

The checks behind the 2026-10-18 full-loop diagnostic. They run the real relay against the live
Tiger DB and Gemini (from the root `.env`), with real speech (Windows SAPI) and the app's real
Detector, LensController, renderer and API client. Every script paces itself for the free-tier
Gemini key (15 requests/min); a paid key lets you lower the pacing.

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

`clarify_rate.py`'s `ERROR(empty body)` label scores the lens rule from before `b4a86d7`; the
current lens shows those answers. Generated files (`wav/`, `utterances.txt`, `results.json`,
`gate_scores.json`, logs) are git-ignored.
