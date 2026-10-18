# Specs v3 — M8 in the native simulator (Part 1)

SDK 0.0.16; official Even Hub simulator (`@evenrealities/sim-win32-x64`); Windows WebView2;
`VITE_MOCK=1`. Flow from `README-V3-PART-1-LENS-UX.md` §6, driven only through the simulator
WebView's dev controls (Nod / Shake buttons and the mock utterance box), no tap, no injected
controller state:

| Frame | Spoken (mock STT) | Lens |
|---|---|---|
| `m8-step-1-of-3` | "walk me through making a cappuccino" | SOP-230 opens at 3.2, scoped `1/3`, `recipe-cup` reference beside the step |
| `m8-clarify` | "next", then "how many pumps of syrup" | CLARIFY "Which size?" Small / Medium / Large |
| `m8-answer` | "medium" | "3 pumps in Medium" with `recipe-pumps`; Shake returns to step 2/3 (3.3), not to the clarify |
| `m8-picture` | "picture" | no relay diagram on 3.3, so STEP_DETAILS with the step's reference picture |
| `m8-done` | "next", "next" | TASK_DONE `3/3 steps` at the end of the cappuccino, not the end of SOP-230 |

`simulator-results.json` is the run's record (45 screen assertions across M1, M2 and M8, 0 console
errors). Preview PNGs composite the simulator's alpha capture onto black, the same method as
`../v2/`. Mock responses: `app/src/mock/index.ts` (`CLARIFY_PUMPS`, `pumpsFor`, `CAPPUCCINO`).

These are UI tests on Part 2's v3 mock contract. They are not a live relay (Part 2 M7), not real
speech, and not hardware (Part 4). Regenerate:

```bash
cd app && VITE_MOCK=1 npx vite --port 5176 --strictPort   # one terminal
node tests/simulator-smoke.mjs                             # another; captures in test-artifacts/v2/
```
