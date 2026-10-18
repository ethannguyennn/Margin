# Margin — iPhone companion (mobile web)

The second display. The lens shows one glance line through the Even Hub bridge; this
is the phone-side surface, so it is a normal browser app and can be seen in the
Base44 preview, on an iPhone over the network, or from a home-screen shortcut.

It talks to the same FastAPI relay as the lens app and imports the same frozen
contract (`ios/src/contract.ts` re-exports `app/src/types.ts`).

## Screens

- **Answer** (`/`) — the whole answer the glance line had to compress: full text,
  citations with quotes, the walkthrough with step navigation, per-stage latency and
  the trace id; plus this session's exchanges.
- **Lens** (`/lens`) — the session panel: session id, listening flag, mic source,
  the procedure/step context the next question is answered against, and a text box
  to ask in words what you would otherwise say out loud. Shows the glance the lens
  would display. `Repeat last` is answered from the relay's own session memory.
- **SOPs** (`/sops`) — procedures and their steps straight from the relay, one tap to
  pin a step as context, and the deviation form (`POST /v1/deviation`).

## Run it

```
cd ios
npm install
VITE_RELAY_ORIGIN=http://localhost:8080 npm run dev   # http://localhost:5175
```

The relay origin has no default: with it unset, the app renders and every call
fails loudly instead of silently pointing somewhere wrong. See `.env.example`.

## What the phone cannot do yet

There is no push channel to the glasses and no session read endpoint: the relay's
`/v1/ask` is still request/response. So the Lens screen drives the relay under this
session — the glasses app starts its own session on launch — and nothing is
delivered to the lens display from here. The screen says so where it matters.
