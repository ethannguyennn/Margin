# Margin lens app

Scaffold based on the official `even-realities/evenhub-templates/asr` template
(template commit recorded in HANDOFF.md). Its browser host, TS config and Vite
structure are retained. Provider-specific STT code and exposed API-key examples
are intentionally replaced by the Margin contracts; Part 2 owns audio/API/obs.

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

`app.json` currently uses **https://margin.example.com**, a non-production
placeholder. Replace it with the agreed relay full HTTPS origin before live
testing. Never ship secrets in VITE variables or add broad whitelist entries.

`npm run build`, `npm test`, `npm run pack` validate/build/package this app.
