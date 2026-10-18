// Env, tunables and the one persisted user setting (mic source).
// Plain `import.meta.env` on purpose: Vite only replaces that exact token at build.
// Tests set process.env at runtime, which vitest's import.meta.env does not see,
// so each key falls back to process.env.
const viteEnv = import.meta.env as Record<string, string | undefined> | undefined;
const nodeEnv = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env ?? {};
export const env = (key: string): string | undefined => viteEnv?.[key] ?? nodeEnv[key];

export const RELAY_ORIGIN = (env('VITE_RELAY_ORIGIN') ?? '').replace(/\/+$/, '');
export const SENTRY_DSN = env('VITE_SENTRY_DSN') ?? '';
export const MOCK = env('VITE_MOCK') === '1';

export const MAX_AUDIO_SECONDS = 8;
export const SAMPLE_RATE = 16000 as const;
export const BYTES_PER_SAMPLE = 2; // pcm_s16le, mono
export const MAX_AUDIO_BYTES = MAX_AUDIO_SECONDS * SAMPLE_RATE * BYTES_PER_SAMPLE;
// Two 20 s generation attempts, with room for transcription, embedding and retrieval.
export const ASK_TIMEOUT_MS = Number(env('VITE_ASK_TIMEOUT_MS') ?? 50000);

/** One id per app launch. Sent as x-session-id on every relay call. */
/** The relay validates this as a UUID, so the fallback must be one too:
 * randomUUID only exists in secure contexts, getRandomValues everywhere. */
export function uuid(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const b = globalThis.crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40; // version 4
  b[8] = (b[8] & 0x3f) | 0x80; // RFC 4122 variant
  const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

export const SESSION_ID: string = uuid();

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
