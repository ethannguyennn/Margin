// IMU on/off, sample normalisation and foreground handling. IMU samples never leave
// the phone: they go to the gesture detector (or the dev recorder) and nowhere else.
//
// Verified against @evenrealities/even_hub_sdk 0.0.16 dist/index.d.ts:
//   imuControl(isOpen: boolean, reportFrq?: ImuReportPace): Promise<boolean>  // P100..P1000
//   sysEvent.eventType === IMU_DATA_REPORT (8), sysEvent.imuData: { x?, y?, z? } (double on wire)
// Measured: evenhub-simulator 0.9.5 does not implement imuControl at all - it throws
// "unknown variant `imuControl`" and the promise never settles. Hence the timeout.
import { MOCK, getImuPace, setImuPace } from '../settings.ts';
import { getBridge } from '../audio/capture.ts';

export type ImuSample = { t: number; x: number; y: number; z: number };

/** Committed fixture / recorder output: compact rows [t_ms, x, y, z]. */
export type ImuFixture = { meta: Record<string, unknown>; samples: [number, number, number, number][] };

const FOREGROUND_ENTER_EVENT = 4;
const FOREGROUND_EXIT_EVENT = 5;
const CONTROL_TIMEOUT_MS = 1500;
// Pace codes are undocumented ("not literal Hz"). Measure what the current one delivers
// and step through the others until one resolves a nod; the choice persists in settings.
const PACES = [500, 1000, 100];
const MIN_HZ = 20;
const PROBE_MS = 1500;
let probe: { untried: number[]; rates: Map<number, number>; t0: number; n: number; last: number } | null = null;

function measure(t: number): void {
  if (!probe) return;
  if (t - probe.last > 1000) probe.n = 0; // the stream paused (pace switch): measure afresh
  probe.last = t;
  if (probe.n++ === 0) probe.t0 = t;
  if (t - probe.t0 < PROBE_MS) return;
  const pace = getImuPace();
  const hz = ((probe.n - 1) * 1000) / (t - probe.t0);
  console.info(`[motion] P${pace}: ${hz.toFixed(0)} samples/s`);
  probe.rates.set(pace, hz);
  const next = hz >= MIN_HZ ? undefined : probe.untried.shift();
  if (next === undefined) {
    const best = [...probe.rates].reduce((a, b) => (b[1] > a[1] ? b : a))[0];
    probe = null;
    if (best !== pace) { setImuPace(best); void control(true, `fastest pace P${best}`); }
    return;
  }
  probe.n = 0;
  setImuPace(next);
  void control(true, `P${pace} too slow for a nod`);
}

const now = (): number => globalThis.performance?.now() ?? Date.now();

/** Protobuf omits zero-valued fields, so a missing axis is 0, not a dropped sample. */
export function toSample(d: { x?: unknown; y?: unknown; z?: unknown } | null | undefined, t: number): ImuSample | null {
  if (!d) return null;
  const v = (a: unknown) => (a === undefined || a === null ? 0 : Number(a));
  const s = { t, x: v(d.x), y: v(d.y), z: v(d.z) };
  return Number.isFinite(s.x) && Number.isFinite(s.y) && Number.isFinite(s.z) ? s : null;
}

export function fixtureSamples(f: ImuFixture): ImuSample[] {
  return f.samples.map(([t, x, y, z]) => ({ t, x, y, z }));
}

type SysEvent = { sysEvent?: { eventType?: number; imuData?: { x?: number; y?: number; z?: number } } };

let sink: ((s: ImuSample) => void) | null = null;
let wanted = false;
let open = false;
let unsubscribe: (() => void) | null = null;

/** The single place imuControl is called. Every call is logged (acceptance: IMU off in background). */
async function control(isOpen: boolean, reason: string): Promise<boolean> {
  const pace = getImuPace();
  console.info(`[motion] imuControl(${isOpen}${isOpen ? `, P${pace}` : ''}) - ${reason}`);
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const b = await getBridge();
    if (!b.imuControl) return false;
    const timeout = new Promise<'timeout'>((r) => (timer = setTimeout(() => r('timeout'), CONTROL_TIMEOUT_MS)));
    const ok = await Promise.race([b.imuControl(isOpen, isOpen ? pace : undefined), timeout]);
    if (ok === 'timeout') console.warn(`[motion] imuControl(${isOpen}) did not answer in ${CONTROL_TIMEOUT_MS} ms`);
    return ok === true;
  } catch (e) {
    console.warn(`[motion] imuControl(${isOpen}) failed`, e);
    return false;
  } finally {
    clearTimeout(timer);
  }
}

async function setOpen(want: boolean, reason: string): Promise<void> {
  if (want === open) return;
  open = want; // flip first: samples stop counting immediately on exit
  if (want) probe = { untried: PACES.filter((p) => p !== getImuPace()), rates: new Map(), t0: 0, n: 0, last: 0 };
  const ok = await control(want, reason);
  if (want && !ok) open = false;
}

function onEvent(e: SysEvent): void {
  const sys = e.sysEvent;
  if (!sys) return;
  if (sys.eventType === FOREGROUND_EXIT_EVENT) void setOpen(false, 'foreground exit');
  else if (sys.eventType === FOREGROUND_ENTER_EVENT) void (wanted && setOpen(true, 'foreground enter'));
  else if (sys.imuData && open) {
    const s = toSample(sys.imuData, now());
    if (s) {
      measure(s.t);
      sink?.(s);
    }
  }
}

if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    const hidden = (document as { visibilityState?: string }).visibilityState === 'hidden';
    if (hidden) void setOpen(false, 'hidden');
    else if (wanted) void setOpen(true, 'visible');
  });
}

/** `?imu=<fixture>` in mock/dev: replay a committed recording instead of the glasses. */
export function replayName(): string | null {
  try {
    return new URLSearchParams(globalThis.location?.search ?? '').get('imu');
  } catch {
    return null;
  }
}

async function startReplay(name: string, onSample: (s: ImuSample) => void): Promise<() => Promise<void>> {
  // Served by the Vite dev server straight from app/tests/; never bundled. Vite answers a
  // missing file with index.html and a 200, so only a JSON content type counts as found.
  const get = async (file: string) => {
    const r = await fetch(`/tests/motion/fixtures/${file}.json`);
    return r.ok && (r.headers.get('content-type') ?? '').includes('json') ? r : null;
  };
  const res = (await get(name)) ?? (await get(`${name}.synthetic`));
  if (!res) {
    console.warn(`[motion] replay fixture ${name} not found`);
    return async () => {};
  }
  const samples = fixtureSamples((await res.json()) as ImuFixture);
  console.info(`[motion] replaying ${name}: ${samples.length} samples`);
  const t0 = samples[0]?.t ?? 0;
  const start = now();
  let i = 0;
  const timer = setInterval(() => {
    const elapsed = now() - start;
    while (i < samples.length && samples[i].t - t0 <= elapsed) {
      const s = samples[i++];
      onSample({ ...s, t: start + s.t - t0 });
    }
    if (i >= samples.length) clearInterval(timer);
  }, 20);
  return async () => clearInterval(timer);
}

/** Start streaming samples. Returns the stop function. Idempotent per caller. */
export async function startImu(onSample: (s: ImuSample) => void): Promise<() => Promise<void>> {
  const replay = replayName();
  if (replay) return startReplay(replay, onSample);
  if (MOCK) {
    // The simulator has no IMU (see top); simulateGesture() drives mock sessions.
    console.info('[motion] mock mode: no IMU. Use ?imu=<fixture> or simulateGesture().');
    return async () => {};
  }
  sink = onSample;
  wanted = true;
  if (!unsubscribe) unsubscribe = (await getBridge()).onEvenHubEvent(onEvent as (e: unknown) => void);
  const hidden = typeof document !== 'undefined' && (document as { visibilityState?: string }).visibilityState === 'hidden';
  if (!hidden) await setOpen(true, 'start');
  return async () => {
    wanted = false;
    sink = null;
    unsubscribe?.();
    unsubscribe = null;
    await setOpen(false, 'stop');
  };
}
