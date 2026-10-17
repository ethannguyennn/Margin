// Env, tunables and the one persisted user setting (mic source).
// Vite injects import.meta.env; node (tests) has neither, so fall back to process.env.
const env = (((import.meta as any).env ?? (globalThis as any).process?.env) ?? {}) as Record<string, string | undefined>;

export const RELAY_ORIGIN = (env.VITE_RELAY_ORIGIN ?? '').replace(/\/+$/, '');
export const SENTRY_DSN = env.VITE_SENTRY_DSN ?? '';
export const MOCK = env.VITE_MOCK === '1';

export const MAX_AUDIO_SECONDS = 8;
export const SAMPLE_RATE = 16000 as const;
export const BYTES_PER_SAMPLE = 2; // pcm_s16le, mono
export const MAX_AUDIO_BYTES = MAX_AUDIO_SECONDS * SAMPLE_RATE * BYTES_PER_SAMPLE;
// 8 s is the contract. Overridable so tests (and a bad hotel network on demo day)
// can tune it without a code change.
export const ASK_TIMEOUT_MS = Number(env.VITE_ASK_TIMEOUT_MS ?? 8000);

/** One id per app launch. Sent as x-session-id on every relay call. */
export const SESSION_ID: string =
  (globalThis.crypto as Crypto | undefined)?.randomUUID?.() ??
  `sess-${Date.now()}-${Math.random().toString(16).slice(2)}`;

// AudioInputSource values from @evenrealities/even_hub_sdk are these exact strings,
// so we use the literals and avoid a runtime import of the SDK here.
export type MicSource = 'glasses' | 'phone';
const MIC_KEY = 'margin.micSource';

export function getMicSource(): MicSource {
  try {
    return localStorage.getItem(MIC_KEY) === 'phone' ? 'phone' : 'glasses';
  } catch {
    return 'glasses'; // storage blocked in the WebView -> default source
  }
}

export function setMicSource(source: MicSource): void {
  try {
    localStorage.setItem(MIC_KEY, source);
  } catch {
    /* non-fatal: the toggle just will not survive a reload */
  }
}
