/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Relay origin; must equal the app.json network whitelist entry exactly. */
  readonly VITE_RELAY_ORIGIN?: string
  /** /v1/ask timeout override in ms (contract default 8000). */
  readonly VITE_ASK_TIMEOUT_MS?: string
  readonly VITE_MOCK?: string
  readonly VITE_SENTRY_DSN?: string
}
