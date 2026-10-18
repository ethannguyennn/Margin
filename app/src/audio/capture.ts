// Capture from the G2 mic array (or the phone mic). v2: a silence endpointer (vad.ts)
// replaces the press-to-send; v1 press-to-talk calls still work unchanged.
// The mic is open ONLY between startCapture and stop/cancel/cap - that is the
// privacy story and the only behaviour that survives Android WebView suspension.
// Raw audio never leaves memory: base64 it, send it, drop the buffer.
import {
  MAX_AUDIO_BYTES,
  MAX_AUDIO_SECONDS,
  MOCK,
  SAMPLE_RATE,
  getMicSource,
  type MicSource,
} from '../settings.ts';
import { mockIsCapturing, mockStartCapture, mockStopCapture } from '../mock/index.ts';
import { Endpointer, type EndpointReason } from './vad.ts';
import { span } from '../obs/sentry.ts';

// Verified against @evenrealities/even_hub_sdk 0.0.x dist/index.d.ts:
//   audioControl(isOpen: boolean, source?: AudioInputSource): Promise<boolean>
//   onEvenHubEvent(cb: (e: EvenHubEvent) => void): () => void
//   AudioEvent { audioPcm: Uint8Array; source: AudioInputSource; direction: number | null;
//                speakerRole: 'self' | 'other' | 'unknown' }
// The SDK normalises audioPcm, but its own doc comment notes the host may send
// number[] or a base64 string, so we accept all three rather than drop audio.
type AudioEvent = {
  audioEvent?: {
    source?: string;
    audioPcm?: Uint8Array | number[] | string;
    direction?: number | null;
    speakerRole?: string;
  };
  sysEvent?: { eventType?: number };
};

const FOREGROUND_ENTER_EVENT = 4; // OsEventTypeList, sdk-reference
const FOREGROUND_EXIT_EVENT = 5;
type Bridge = {
  audioControl: (isOpen: boolean, source?: string) => Promise<boolean>;
  onEvenHubEvent: (cb: (e: AudioEvent) => void) => () => void;
  imuControl?: (isOpen: boolean, reportFrq?: number) => Promise<boolean>; // motion/imu.ts
};

let bridge: Bridge | null = null;

/** Test seam, and the hook Part 1 can use to inject the already-built bridge. */
export function setBridge(b: Bridge | null): void {
  bridge = b;
}

/** Shared with motion/imu.ts so the app holds one bridge. */
export async function getBridge(): Promise<Bridge> {
  if (bridge) return bridge;
  // Dynamic import: keeps this module loadable (and testable) without the SDK,
  // and guarantees Part 1's createStartUpPageContainer has run first - the
  // Glasses source fails if it has not.
  const sdk = (await import('@evenrealities/even_hub_sdk')) as {
    waitForEvenAppBridge: () => Promise<Bridge>;
  };
  bridge = await sdk.waitForEvenAppBridge();
  return bridge;
}

let capturing = false; // the mic is open right now
// The press is in progress: true from startCapture until stopCapture/cancel, even
// after the 8 s cap has already closed the mic. Without this, the user's stop
// press after a cap reads as a new press, reopens the mic and loses the audio.
let session = false;
let chunks: Uint8Array[] = [];
let bytes = 0;
let unsubscribe: (() => void) | null = null;
let capTimer: ReturnType<typeof setTimeout> | null = null;
let level: ((rms01: number) => void) | null = null;
// Per-press tally of the SDK's speakerRole tags. Not used to filter audio - a
// misclassified 'other' would eat the technician's own question - but logged so
// the glasses-vs-phone mic A/B has numbers behind it.
let roles: Record<string, number> = {};
// v2 endpointing: the press-to-send is gone, so capture decides when the worker stopped.
const PRE_ROLL_MS = 200; // kept before the speech start so the first word is not clipped
const BYTES_PER_MS = (SAMPLE_RATE * 2) / 1000;
let endpointer: Endpointer | null = null;
let endpointCb: ((reason: EndpointReason) => void) | null = null;
let noSpeech = false;
let openedAt = 0;

export function isCapturing(): boolean {
  return MOCK ? mockIsCapturing() : session;
}

function toU8(pcm: Uint8Array | number[] | string): Uint8Array {
  if (pcm instanceof Uint8Array) return pcm;
  if (typeof pcm !== 'string') return new Uint8Array(pcm);
  const bin = (globalThis as { atob?: (s: string) => string }).atob?.(pcm) ?? '';
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

/** 0..1 RMS over signed 16-bit LE samples. */
function rms01(buf: Uint8Array): number {
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const n = Math.floor(buf.byteLength / 2);
  if (n === 0) return 0;
  let sum = 0;
  for (let i = 0; i < n; i++) {
    const s = view.getInt16(i * 2, true) / 32768;
    sum += s * s;
  }
  return Math.min(1, Math.sqrt(sum / n));
}

function base64(buf: Uint8Array): string {
  const g = globalThis as { btoa?: (s: string) => string; Buffer?: { from: (b: Uint8Array) => { toString: (e: string) => string } } };
  if (!g.btoa) return g.Buffer!.from(buf).toString('base64'); // node, tests only
  let s = '';
  for (let i = 0; i < buf.length; i += 0x8000) {
    s += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  }
  return g.btoa(s);
}

/** The single place the mic is closed. Logged so the acceptance check is auditable. */
async function closeMic(reason: string): Promise<void> {
  if (capTimer) clearTimeout(capTimer);
  capTimer = null;
  if (unsubscribe) unsubscribe();
  unsubscribe = null;
  level = null;
  if (!capturing) return;
  capturing = false;
  console.info(`[audio] audioControl(false) - ${reason}`, { bytes, seconds: +(bytes / 32000).toFixed(2), roles });
  try {
    await (await getBridge()).audioControl(false);
  } catch (e) {
    console.warn('[audio] audioControl(false) failed', e);
  }
}

/** At most one endpoint per press. The mic closes on every endpoint; Part 1 then calls stopCapture. */
function endpointReached(reason: EndpointReason): void {
  const cb = endpointCb;
  endpointCb = null;
  if (reason === 'no_speech') noSpeech = true;
  console.info(`[audio] endpoint ${reason}`, { speechStartMs: endpointer?.speechStartMs ?? null });
  span('endpoint', openedAt, { reason });
  void closeMic(`endpoint ${reason}`);
  cb?.(reason);
}

function onAudio(e: AudioEvent): void {
  // The host's own lifecycle signal; visibilitychange below is the backup.
  const sys = e.sysEvent?.eventType;
  if (sys === FOREGROUND_EXIT_EVENT || sys === FOREGROUND_ENTER_EVENT) {
    void cancelCapture();
    return;
  }
  const pcm = e.audioEvent?.audioPcm;
  if (!pcm || !capturing) return;
  const role = e.audioEvent?.speakerRole;
  if (role) roles[role] = (roles[role] ?? 0) + 1;
  let buf = toU8(pcm);
  const room = MAX_AUDIO_BYTES - bytes;
  if (buf.byteLength >= room) {
    buf = buf.subarray(0, room); // 8 s cap: a 20 s press still sends 8 s
  }
  if (buf.byteLength > 0) {
    chunks.push(buf);
    bytes += buf.byteLength;
    const r = rms01(buf);
    level?.(r);
    const reason = endpointer?.push(r, buf.byteLength / BYTES_PER_MS);
    if (reason) return endpointReached(reason);
  }
  if (bytes >= MAX_AUDIO_BYTES) {
    if (endpointCb) endpointReached('cap');
    else void closeMic(`cap ${MAX_AUDIO_SECONDS}s reached`);
  }
}

/** onEndpoint (v2) fires once: 'speech_end' after 800 ms of silence, 'no_speech' when nothing
 * was said within 3 s (stopCapture then returns data_b64 '' - do not ask), 'cap' at 8 s. */
export async function startCapture(
  onLevel: (rms01: number) => void,
  onEndpoint?: (reason: EndpointReason) => void,
): Promise<void> {
  if (MOCK) return mockStartCapture(onLevel, onEndpoint);
  if (session) return;

  chunks = [];
  bytes = 0;
  roles = {};
  level = onLevel;
  endpointer = new Endpointer();
  endpointCb = onEndpoint ?? null;
  noSpeech = false;
  openedAt = Date.now();
  const source: MicSource = getMicSource();
  const b = await getBridge();

  // Subscribe before opening the mic so no leading chunk is dropped, and
  // subscribe fresh every press - after a WebView suspension the old
  // subscription is dead.
  unsubscribe = b.onEvenHubEvent(onAudio);
  console.info(`[audio] audioControl(true, '${source}')`);
  let ok = false;
  try {
    ok = await b.audioControl(true, source);
  } catch (e) {
    unsubscribe();
    unsubscribe = null;
    level = null;
    throw new Error(`Microphone unavailable (${source}): ${(e as Error)?.message ?? 'bridge error'}`);
  }
  if (!ok) {
    unsubscribe();
    unsubscribe = null;
    level = null;
    throw new Error(
      source === 'glasses'
        ? 'Glasses mic unavailable. Check the g2-microphone permission and that the glasses are connected.'
        : 'Phone mic permission denied. Enable it in system settings.',
    );
  }
  capturing = true;
  session = true;
  // Wall-clock backstop: if chunks stop arriving we still close the mic.
  capTimer = setTimeout(() => {
    if (endpointCb) endpointReached('cap');
    else void closeMic(`cap ${MAX_AUDIO_SECONDS}s timer`);
  }, MAX_AUDIO_SECONDS * 1000);
}

export async function stopCapture(): Promise<{ data_b64: string; sample_rate: 16000 }> {
  if (MOCK) return mockStopCapture();
  await closeMic('stopCapture');
  session = false;
  endpointCb = null;
  const all = new Uint8Array(bytes);
  let off = 0;
  for (const c of chunks) {
    all.set(c, off);
    off += c.byteLength;
  }
  chunks = []; // drop the buffer: nothing is persisted, ever
  bytes = 0;
  // Nobody spoke: a stray nod costs 3 s of open mic and zero network.
  if (noSpeech) return { data_b64: '', sample_rate: SAMPLE_RATE };
  // Trim leading silence (smaller upload, faster STT). A manual stop before the VAD saw
  // speech sends everything: in a loud shop the energy VAD may simply have missed it.
  const start = endpointer?.speechStartMs;
  const cut = start == null ? 0 : Math.max(0, Math.round((start - PRE_ROLL_MS) * BYTES_PER_MS)) & ~1;
  return { data_b64: base64(all.subarray(cut)), sample_rate: SAMPLE_RATE };
}

/** Double-press cancel: close the mic and throw the audio away. */
export async function cancelCapture(): Promise<void> {
  if (MOCK) {
    await mockStopCapture();
    return;
  }
  await closeMic('cancelCapture');
  session = false;
  endpointCb = null;
  chunks = [];
  bytes = 0;
}

// Android may suspend the WebView at any moment. Never assume a live stream:
// on any visibility change, close the mic and drop the buffer. The next press
// re-subscribes and re-enables from scratch.
if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    void cancelCapture();
  });
}
