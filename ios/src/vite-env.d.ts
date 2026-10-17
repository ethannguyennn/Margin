/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Relay origin, e.g. https://8000-<preview host>. Empty = every call fails loudly. */
  readonly VITE_RELAY_ORIGIN?: string
  /** /v1/ask timeout override in ms (contract default 8000). */
  readonly VITE_ASK_TIMEOUT_MS?: string
}
