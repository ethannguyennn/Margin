# Specs Even Hub app

One Even Hub app, two screens, one session:

- **Lens** (glasses): `src/main.ts` + `src/state.ts` + `src/ui/`, drawn through the SDK
  bridge (text containers, gestures, glasses mic).
- **Phone** (`src/phone/`, React): the companion screen the Even app shows in its WebView,
  formerly `ios/`. Answer (the full text the glance compresses, citations, walkthrough,
  latency, trace id), Lens (glasses status, push-to-talk, mic source, typed questions,
  a live mirror of the lens text) and SOPs (procedures, steps, deviation form).

`src/lens-link.ts` is the only seam between them: the lens publishes its state and every
relay answer; the phone sends typed questions (answered on the glasses too, through the
same controller path as speech) and push-to-talk. In a plain browser there is no Even
bridge, so the phone screen runs standalone and asks the relay directly; `npm run dev`
and opening http://localhost:5174 is the browser preview. Routes are hash-based
(`#/lens`, `#/sops`) and Vite uses `base: './'` so the packaged `.ehpk` resolves both.

Scaffold based on the official `even-realities/evenhub-templates/asr` template
(template commit recorded in HANDOFF.md). Its browser host, TS config and Vite
structure are retained. Provider-specific STT code and exposed API-key examples
are intentionally replaced by the Specs contracts; Part 2 owns audio/API/obs.

Use Node 22.12+ (tested with Node 24). On Windows use `npm.cmd` if PowerShell
execution policy blocks `npm`.

```sh
npm install
npm run dev:mock
# second terminal
npm run simulate
```

Port 5174 avoids the user's existing starter on 5173. Real glasses require Even
App 2.2.10+, Developer Mode and a reachable LAN URL generated with `evenhub qr`.

`app.json` currently uses **https://specs.example.com**, a non-production
placeholder. Replace it with the agreed relay full HTTPS origin before live
testing. Never ship secrets in VITE variables or add broad whitelist entries.

`npm run build`, `npm test`, `npm run pack` validate/build/package this app.

## Fixture demo

`npm run dev:mock` sets `VITE_MOCK=1` using `.env.mock`. Alternatively in
PowerShell: `$env:VITE_MOCK='1'; npm run dev`.

Press once to acknowledge privacy on first launch. Press to listen, press to
send. The fixture-only development adapter cycles through **answer -> not
found -> error -> walkthrough -> logged**, one per question. It records no
audio and makes no relay request. Double press dismisses an outcome, and
double press at IDLE opens native exit confirmation.

- Answer: press to expand/collapse, up/down changes detail pages, double press
  in details collapses, then double press dismisses to IDLE.
- Walkthrough: up/down changes steps locally; press opens step details;
  press/double press returns to that step. No request is made on a swipe.
- Long press and long-press release are deliberately unused.
- Glance dims after 20 seconds. Other temporary screens time out at 60 seconds.
  Walkthrough and its details persist; cold-start restore accepts only a
  walkthrough received less than 30 minutes earlier.

The UI fixtures are in `src/ui/fixtures.ts`, **not** Part 2's mock layer. When
Part 2's three frozen modules are present, `main.ts` delegates to them in both
live and mock mode. Until then, live mode fails safely to ERROR. Real audio,
relay, Sentry, and Part 2's mock module have not been integration-tested here.

## Reproduce acceptance tests

Use a freshly launched simulator session at `http://localhost:5174`. The smoke
test sends only official simulator gesture inputs; it does not inject app
states. It intentionally ends with native shutdown.

```sh
npm test
npm run test:coverage
npm run build
npm run test:simulator
```

The last command requires the dev server and simulator already running. Full
console logs, result JSON and original PNG captures go into ignored
`test-artifacts/`. On Windows run `./tests/render-simulator-captures.ps1` to
generate black-background previews: the simulator's original glasses PNGs
encode brightness in alpha with a constant green RGB plane. Both originals
and previews are retained. Selected tested captures and the acceptance result
are in `tests/evidence/`.

The simulator accepts `shutDownPageContainer(1)` and clears the active page;
version 0.9.5 did not emit SYSTEM_EXIT_EVENT in the tested run. Real-hardware
confirmation, font coverage and brightness still need device testing.

See `HANDOFF.md` for the scaffold tag, contracts, fixtures, and integration
boundaries. The relay origin remains the approved placeholder until supplied.
