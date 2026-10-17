// Push-to-talk capture from the G2 mic array (or the phone mic).
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

type AudioEvent = { audioEvent?: { source?: string; audioPcm?: Uint8Array | number[] } };
type Bridge = {
  audioControl: (isOpen: boolean, source?: string) => Promise<boolean>;
  onEvenHubEvent: (cb: (e: AudioEvent) => void) => () => void;
};

let bridge: Bridge | null = null;

/** Test seam, and the hook Part 1 can use to inject the already-built bridge. */
export function setBridge(b: Bridge | null): void {
  bridge = b;
}

async function getBridge(): Promise<Bridge> {
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

let capturing = false;
let chunks: Uint8Array[] = [];
let bytes = 0;
let unsubscribe: (() => void) | null = null;
let capTimer: ReturnType<typeof setTimeout> | null = null;
let level: ((rms01: number) => void) | null = null;

export function isCapturing(): boolean {
  return MOCK ? mockIsCapturing() : capturing;
}

function toU8(pcm: Uint8Array | number[]): Uint8Array {
  return pcm instanceof Uint8Array ? pcm : new Uint8Array(pcm);
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
  console.info(`[audio] audioControl(false) - ${reason}`);
  try {
    await (await getBridge()).audioControl(false);
  } catch (e) {
    console.warn('[audio] audioControl(false) failed', e);
  }
}

function onAudio(e: AudioEvent): void {
  const pcm = e.audioEvent?.audioPcm;
  if (!pcm || !capturing) return;
  let buf = toU8(pcm);
  const room = MAX_AUDIO_BYTES - bytes;
  if (buf.byteLength >= room) {
    buf = buf.subarray(0, room); // 8 s cap: a 20 s press still sends 8 s
  }
  if (buf.byteLength > 0) {
    chunks.push(buf);
    bytes += buf.byteLength;
    level?.(rms01(buf));
  }
  if (bytes >= MAX_AUDIO_BYTES) void closeMic(`cap ${MAX_AUDIO_SECONDS}s reached`);
}

export async function startCapture(onLevel: (rms01: number) => void): Promise<void> {
  if (MOCK) return mockStartCapture(onLevel);
  if (capturing) return;

  chunks = [];
  bytes = 0;
  level = onLevel;
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
  // Wall-clock backstop: if chunks stop arriving we still close the mic.
  capTimer = setTimeout(() => void closeMic(`cap ${MAX_AUDIO_SECONDS}s timer`), MAX_AUDIO_SECONDS * 1000);
}

export async function stopCapture(): Promise<{ data_b64: string; sample_rate: 16000 }> {
  if (MOCK) return mockStopCapture();
  await closeMic('stopCapture');
  const all = new Uint8Array(bytes);
  let off = 0;
  for (const c of chunks) {
    all.set(c, off);
    off += c.byteLength;
  }
  chunks = []; // drop the buffer: nothing is persisted, ever
  bytes = 0;
  return { data_b64: base64(all), sample_rate: SAMPLE_RATE };
}

/** Double-press cancel: close the mic and throw the audio away. */
export async function cancelCapture(): Promise<void> {
  if (MOCK) {
    await mockStopCapture();
    return;
  }
  await closeMic('cancelCapture');
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
