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
// 8 s is the contract. Overridable so tests (and a bad hotel network on demo day)
// can tune it without a code change.
export const ASK_TIMEOUT_MS = Number(env('VITE_ASK_TIMEOUT_MS') ?? 8000);

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
const MIC_KEY = 'specs.micSource';

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

// --- v2: device credentials, gesture tuning ---------------------------------
// localStorage is the only storage the WebView has; it is sandboxed per package_id.
// Every read/write is wrapped: a blocked store must degrade, never crash.
function load<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}
function save(key: string, value: unknown): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* non-fatal: survives this session only */
  }
}

/** This device's relay credential. The token authorises this device only; never logged. */
export type DeviceCredential = { device_id: string; device_token: string };
const DEVICE_KEY = 'specs.device';
export const getDevice = (): DeviceCredential | null => {
  const d = load<DeviceCredential | null>(DEVICE_KEY, null);
  return d && typeof d.device_token === 'string' && d.device_token ? d : null;
};
export const setDevice = (d: DeviceCredential | null): void => save(DEVICE_KEY, d);

/** Per-wearer detector overrides written by calibrate(); merged over DEFAULT_PARAMS. */
const PARAMS_KEY = 'specs.detector';
export const getDetectorOverrides = (): Record<string, unknown> | null => load(PARAMS_KEY, null);
export const setDetectorOverrides = (p: Record<string, unknown> | null): void => save(PARAMS_KEY, p);

/** 0.5 (stiffer) .. 2 (more sensitive). Divides the amplitude thresholds. */
const SENS_KEY = 'specs.sensitivity';
export const getSensitivity = (): number => {
  const s = Number(load(SENS_KEY, 1));
  return Number.isFinite(s) ? Math.min(2, Math.max(0.5, s)) : 1;
};
export const setSensitivity = (s: number): void => save(SENS_KEY, Math.min(2, Math.max(0.5, s)));

/** 'single' stays off until the M4 false-positive data says it is safe. */
export type NodMode = 'double' | 'single';
const NOD_KEY = 'specs.nodMode';
export const getNodMode = (): NodMode => (load<string>(NOD_KEY, 'double') === 'single' ? 'single' : 'double');
export const setNodMode = (m: NodMode): void => save(NOD_KEY, m);

/** ImuReportPace code (100..1000). A protocol code, not Hz; the default is provisional
 * until the hardware characterisation picks the lowest pace that resolves a nod. */
const PACE_KEY = 'specs.imuPace';
export const getImuPace = (): number => {
  const p = Number(load(PACE_KEY, 500));
  return [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000].includes(p) ? p : 500;
};
export const setImuPace = (p: number): void => save(PACE_KEY, p);
