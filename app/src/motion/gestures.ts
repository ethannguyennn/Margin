// Head gestures from the G2 IMU. One streaming Detector does all the work; detect() runs
// it over an array (tests, fixtures) and startHeadGestures() feeds it live samples.
//
// Everything the hardware decides (which axis is pitch, whether x/y/z are angles or
// rates, units) is a knob in DetectorParams, set from the recordings - see
// docs/handoffs/PART-2.md. Every threshold is a knob too, persisted per wearer by
// calibrate() through settings.ts. Nothing here leaves the phone.
import type { ImuSample } from './imu.ts';
import { replayName, startImu } from './imu.ts';
import {
  MOCK,
  getDetectorOverrides,
  getNodMode,
  getSensitivity,
  setDetectorOverrides,
} from '../settings.ts';
import { span } from '../obs/sentry.ts';

export type HeadGesture = 'NOD' | 'SHAKE';
export type Axis = 'x' | 'y' | 'z';

export interface DetectorParams {
  // --- what the IMU reports (hardware facts from the characterisation, not guesses)
  pitchAxis: Axis;
  pitchSign: 1 | -1; // so that looking down is negative
  yawAxis: Axis;
  yawSign: 1 | -1;
  // 'angle' is differentiated; 'rate' is used as is; 'accel' is a gravity vector turned into
  // degrees of tilt; 'auto' picks 'accel' when the first sample has gravity's magnitude.
  signal: 'auto' | 'angle' | 'rate' | 'accel';
  scale: number; // raw units -> degrees (or deg/s for 'rate')
  wrap: number; // angle period after scale (360); 0 = no wrap handling
  restMs: number; // 'accel': how slowly the rest (posture) direction follows the head
  // --- filtering
  lpMs: number; // low-pass time constant
  hpMs: number; // bias removal for a gyro; 0 = off
  maxGapMs: number; // a gap longer than this resets the detector
  lobeEnd: number; // a lobe ends when |rate| falls below lobeEnd x its threshold
  // --- nod (deg/s on the pitch rate)
  down: number; // down-movement lobe threshold
  up: number; // return lobe threshold
  nodMinMs: number; // down-lobe onset -> up-lobe onset
  nodMaxMs: number;
  doubleMinMs: number; // nod -> nod, for the double nod
  doubleMaxMs: number;
  // --- shake (deg/s on the yaw rate)
  yaw: number;
  shakeMs: number; // 3 alternating yaw lobes (>= 2 reversals) within this window
  // --- rejection
  quietRatio: number; // off-axis peak must stay below this x the gesture axis peak
  gate: number; // RMS rate (all axes) in the window before onset above this = whole-body motion
  gateMs: number;
  gateLeadMs: number; // the window ends this long before onset: a gesture moves before it crosses a threshold
  cooldownMs: number;
  single: boolean; // emit NOD on a single nod (off until M4 says it is safe)
}

// The G2 reports a gravity-normalised accelerometer (|v| ~ 1 g at rest; reverse-engineered
// in github.com/mmirman/open-g2-companion), so 'auto' lands on 'accel', which needs no axis
// mapping. The axis knobs only matter for 'angle'/'rate' data (the synthetic fixtures).
export const DEFAULT_PARAMS: DetectorParams = {
  pitchAxis: 'x',
  pitchSign: 1,
  yawAxis: 'y',
  yawSign: 1,
  signal: 'auto',
  scale: 1,
  wrap: 360,
  restMs: 3000,
  lpMs: 40,
  hpMs: 0,
  maxGapMs: 300,
  lobeEnd: 0.3,
  // As low as the motion gate and the walking-train check allow: a double nod is never
  // accidental, so sensitivity wins. 22/18 caught 5-9 deg nods at 25 Hz in BLE bursts with
  // no false trigger on still, walking or bench work (synthetic, 5 noise seeds).
  down: 22,
  up: 18,
  nodMinMs: 60,
  nodMaxMs: 600,
  doubleMinMs: 250,
  doubleMaxMs: 1200,
  yaw: 50,
  shakeMs: 1000,
  quietRatio: 0.6,
  gate: 20,
  gateMs: 700,
  gateLeadMs: 200,
  cooldownMs: 1500,
  single: false,
};

type Lobe = { sign: 1 | -1; t0: number; open: boolean; peak: number; nod?: { down: number } };
type Filtered = { t: number; p: number; y: number; r: number };
export type NodInfo = { t: number; down: number; up: number };

const HISTORY_MS = 3000;
type Vec = { x: number; y: number; z: number };
/** 1 g, in g or in m/s^2. Euler angles or gyro rates of a still head are near 0 instead. */
const gravityLike = (s: Vec): boolean => {
  const m = Math.hypot(s.x, s.y, s.z);
  return (m > 0.75 && m < 1.25) || (m > 7.5 && m < 12);
};
const lerp = (a: Vec, b: Vec, k: number): Vec => ({ x: a.x + k * (b.x - a.x), y: a.y + k * (b.y - a.y), z: a.z + k * (b.z - a.z) });
const unit = (v: Vec): Vec => {
  const n = Math.hypot(v.x, v.y, v.z) || 1;
  return { x: v.x / n, y: v.y / n, z: v.z / n };
};

export class Detector {
  private prev: { t: number; p: number; y: number; r: number } | null = null;
  private t0 = 0; // first arrival since the stream (re)started
  private n = 0; // samples since then
  private lp = { p: 0, y: 0, r: 0 };
  private bias = { p: 0, y: 0, r: 0 };
  private hist: Filtered[] = [];
  private pitch: Lobe | null = null;
  private yawCur: Lobe | null = null;
  private yawLobes: Lobe[] = [];
  private lastNod: { start: number; t: number; busy: boolean } | null = null;
  private lobeStarts: number[] = [];
  private lastEmit = -Infinity;
  private readonly roll: Axis;
  private mode: Exclude<DetectorParams['signal'], 'auto'> | null = null;
  private rest: Vec | null = null;
  private grav: Vec | null = null;

  /** onNod reports every single nod's peak rates once its return lobe ends (calibration). */
  constructor(
    readonly params: DetectorParams,
    private readonly onNod?: (n: NodInfo) => void,
  ) {
    this.roll = (['x', 'y', 'z'] as const).find((a) => a !== params.pitchAxis && a !== params.yawAxis)!;
  }

  private reset(): void {
    this.prev = null;
    this.lp = { p: 0, y: 0, r: 0 };
    this.bias = { p: 0, y: 0, r: 0 };
    this.hist = [];
    this.pitch = this.yawCur = this.lastNod = null;
    this.lobeStarts = [];
    this.yawLobes = [];
    this.rest = this.grav = null;
  }

  /** Degrees between gravity now and the slow rest direction, negated so a nod reads as a
   * down lobe then its return. No axis or sign mapping; yaw is invisible to gravity, so an
   * accelerometer gives no SHAKE (double press covers "back"). */
  private tilt(s: ImuSample, dt: number): number {
    const m = Math.hypot(s.x, s.y, s.z) || 1;
    // Low-pass the gravity direction before taking the angle: the angle is unsigned, so
    // noise taken through it first would rectify into a jittery tilt that reads as motion.
    const a = this.grav ? dt / (this.params.lpMs + dt) : 1;
    const u = unit(lerp(this.grav ?? { x: 0, y: 0, z: 0 }, { x: s.x / m, y: s.y / m, z: s.z / m }, a));
    this.grav = u;
    const rest = this.rest ?? u;
    const deg = (Math.acos(Math.min(1, Math.max(-1, u.x * rest.x + u.y * rest.y + u.z * rest.z))) * 180) / Math.PI;
    // Rest holds during a pitch lobe: drifting toward the first nod of a double put the head
    // "above" rest for the second, which then started with a reversal.
    this.rest = this.pitch?.open ? rest : unit(lerp(rest, u, Math.min(1, dt / this.params.restMs)));
    return -deg;
  }

  push(s: ImuSample): HeadGesture | null {
    const P = this.params;
    if (!this.mode) {
      this.mode = P.signal !== 'auto' ? P.signal : gravityLike(s) ? 'accel' : 'angle';
      console.info(`[motion] IMU signal: ${this.mode}`);
    }
    const prev = this.prev;
    const gap = !prev || s.t - prev.t > P.maxGapMs || s.t < prev.t;
    if (gap) {
      this.reset();
      this.t0 = s.t;
      this.n = 0;
    } else this.n++;
    // BLE delivers in bursts: several samples share one arrival time and the next burst
    // comes a whole burst later. The IMU itself samples evenly, so the interval is the mean
    // since the stream (re)started, not the gap to the previous arrival (which read a nod
    // in bursts of 3 at a third of its speed).
    const dt = this.n ? (s.t - this.t0) / this.n : 0;
    const raw = this.mode === 'accel' ? { t: s.t, p: this.tilt(s, dt), y: 0, r: 0 } : {
      t: s.t,
      p: s[P.pitchAxis] * P.scale * P.pitchSign,
      y: s[P.yawAxis] * P.scale * P.yawSign,
      r: s[this.roll] * P.scale,
    };
    this.prev = raw;
    if (!prev || gap || dt < 1) return null;
    const rate = (k: 'p' | 'y' | 'r'): number => {
      if (this.mode === 'rate') return raw[k];
      let d = raw[k] - prev[k];
      if (P.wrap) d -= P.wrap * Math.round(d / P.wrap); // 179 -> -179 is +2, not -358
      return (d / dt) * 1000;
    };
    const a = this.mode === 'accel' ? 1 : dt / (P.lpMs + dt); // accel: tilt() already low-passed
    const b = P.hpMs > 0 ? dt / (P.hpMs + dt) : 0;
    const f: Filtered = { t: s.t, p: 0, y: 0, r: 0 };
    for (const k of ['p', 'y', 'r'] as const) {
      this.lp[k] += a * (rate(k) - this.lp[k]);
      this.bias[k] += b * (this.lp[k] - this.bias[k]);
      f[k] = this.lp[k] - this.bias[k];
    }
    this.hist.push(f);
    while (this.hist[0].t < s.t - HISTORY_MS) this.hist.shift();

    return this.pitchStep(f) ?? this.yawStep(f);
  }

  /** Max |value| per axis over [from, to]. */
  private peaks(from: number, to: number): Filtered {
    const m: Filtered = { t: 0, p: 0, y: 0, r: 0 };
    for (const h of this.hist) {
      if (h.t < from || h.t > to) continue;
      m.p = Math.max(m.p, Math.abs(h.p));
      m.y = Math.max(m.y, Math.abs(h.y));
      m.r = Math.max(m.r, Math.abs(h.r));
    }
    return m;
  }

  private pitchStep(f: Filtered): HeadGesture | null {
    const P = this.params;
    const cur = this.pitch;
    if (cur?.open) {
      if (f.p * cur.sign < P.lobeEnd * (cur.sign < 0 ? P.down : P.up)) {
        cur.open = false;
        if (cur.nod) this.onNod?.({ t: f.t, down: cur.nod.down, up: cur.peak });
      } else {
        cur.peak = Math.max(cur.peak, Math.abs(f.p));
        return null;
      }
    }
    const sign = f.p <= -P.down ? -1 : f.p >= P.up ? 1 : 0;
    if (!sign) return null;
    const lobe: Lobe = { sign, t0: f.t, open: true, peak: Math.abs(f.p) };
    this.pitch = lobe;
    this.lobeStarts = [...this.lobeStarts.filter((t) => t >= f.t - HISTORY_MS), f.t];
    // A nod: a down lobe, then the return lobe soon after, with yaw and roll quiet.
    if (sign !== 1 || cur?.sign !== -1) return null;
    const gap = f.t - cur.t0;
    if (gap < P.nodMinMs || gap > P.nodMaxMs) return null;
    const pk = this.peaks(cur.t0, f.t);
    if (Math.max(pk.y, pk.r) >= P.quietRatio * pk.p) return null;
    lobe.nod = { down: cur.peak };
    // Walking bobs the head in a steady train of nod-like lobes; a deliberate nod starts from
    // a still head. Any lobe in the gate window before the down lobe = part of a train.
    const from = cur.t0 - P.gateLeadMs - P.gateMs;
    const busy = this.lobeStarts.some((t) => t >= from && t < cur.t0 - P.gateLeadMs);
    const nod = { start: cur.t0, t: f.t, busy };
    if (P.single) return busy ? null : this.emit('NOD', nod.start, f.t);
    const first = this.lastNod;
    this.lastNod = nod;
    if (!first || first.busy) return null;
    const between = nod.t - first.t;
    if (between < P.doubleMinMs || between > P.doubleMaxMs) return null;
    this.lastNod = null;
    return this.emit('NOD', first.start, f.t);
  }

  private yawStep(f: Filtered): HeadGesture | null {
    const P = this.params;
    const cur = this.yawCur;
    if (cur?.open) {
      if (f.y * cur.sign < P.lobeEnd * P.yaw) cur.open = false;
      else return null;
    }
    const sign = f.y <= -P.yaw ? -1 : f.y >= P.yaw ? 1 : 0;
    if (!sign) return null;
    const lobe: Lobe = { sign, t0: f.t, open: true, peak: Math.abs(f.y) };
    this.yawCur = lobe;
    this.yawLobes = [...this.yawLobes.filter((l) => l.t0 >= f.t - P.shakeMs), lobe].slice(-3);
    const [l1, l2, l3] = this.yawLobes;
    if (!l3 || l1.sign === l2.sign || l2.sign === l3.sign) return null;
    const pk = this.peaks(l1.t0, f.t);
    if (pk.p >= P.quietRatio * pk.y) return null;
    this.yawLobes = [];
    return this.emit('SHAKE', l1.t0, f.t);
  }

  /** Cooldown and the whole-body motion gate apply to every gesture. */
  private emit(g: HeadGesture, onset: number, t: number): HeadGesture | null {
    const P = this.params;
    if (t - this.lastEmit < P.cooldownMs) return null;
    let sum = 0;
    let n = 0;
    for (const h of this.hist) {
      if (h.t < onset - P.gateLeadMs - P.gateMs || h.t >= onset - P.gateLeadMs) continue;
      sum += h.p * h.p + h.y * h.y + h.r * h.r;
      n++;
    }
    if (n && Math.sqrt(sum / n) > P.gate) return null;
    this.lastEmit = t;
    return g;
  }
}

/** Pure: samples -> gestures. The test suite runs this over the committed fixtures. */
export function detect(samples: ImuSample[], params: DetectorParams): { t: number; g: HeadGesture }[] {
  const d = new Detector(params);
  const out: { t: number; g: HeadGesture }[] = [];
  for (const s of samples) {
    const g = d.push(s);
    if (g) out.push({ t: s.t, g });
  }
  return out;
}

const KNOBS = Object.keys(DEFAULT_PARAMS) as (keyof DetectorParams)[];

/** Defaults, then this wearer's persisted overrides, then the sensitivity slider and nod mode. */
export function currentParams(): DetectorParams {
  const p: DetectorParams = { ...DEFAULT_PARAMS };
  const o = getDetectorOverrides() ?? {};
  for (const k of KNOBS) {
    if (typeof o[k] === typeof p[k]) (p as unknown as Record<string, unknown>)[k] = o[k];
  }
  const s = getSensitivity();
  p.down /= s;
  p.up /= s;
  p.yaw /= s;
  p.single = getNodMode() === 'single';
  return p;
}

// --- stateful wrapper: the surface Part 1 codes against ----------------------
let listener: ((g: HeadGesture) => void) | null = null;
let sink: ((s: ImuSample) => void) | null = null;
let stopImu: (() => Promise<void>) | null = null;
let starting: Promise<void> | null = null;

function fire(g: HeadGesture, source: 'imu' | 'simulated', onsetMs?: number): void {
  console.info(`[motion] gesture ${g} (${source})`);
  span('gesture', onsetMs, { gesture: g, source });
  listener?.(g);
}

function liveSink(): (s: ImuSample) => void {
  const d = new Detector(currentParams());
  return (s) => {
    const g = d.push(s);
    if (g) fire(g, 'imu');
  };
}

async function ensureImu(): Promise<void> {
  if (stopImu) return;
  starting ??= startImu((s) => sink?.(s)).then((stop) => {
    stopImu = stop;
  });
  try {
    await starting;
  } finally {
    starting = null;
  }
}

export async function startHeadGestures(onGesture: (g: HeadGesture) => void): Promise<void> {
  listener = onGesture;
  sink = liveSink();
  await ensureImu();
}

export async function stopHeadGestures(): Promise<void> {
  listener = null;
  sink = null;
  const stop = stopImu;
  stopImu = null;
  await stop?.();
}

/** Dev buttons and tests: delivered like a detected gesture, no cooldown. */
export function simulateGesture(g: HeadGesture): void {
  fire(g, 'simulated');
}

// Mock sessions without ?imu= replay have no IMU to calibrate against (the simulator has none).
let mockCalibrated = false;

export function isCalibrated(): boolean {
  return mockCalibrated || getDetectorOverrides()?.calibrated === true;
}

const median = (xs: number[]): number => {
  const s = [...xs].sort((a, b) => a - b);
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
};

/**
 * Prompt for 3 double nods (Part 1 shows the prompt), then set down/up to 60 % of this
 * wearer's median peak rates, never above the defaults (calibration only ever makes the
 * detector more sensitive). Nods too weak to clear the floor (60 % of the defaults)
 * keep the defaults and return ok: false. Gestures are not emitted while calibrating.
 */
export async function calibrate(
  onProgress: (done: number, needed: number) => void,
  opts: { timeoutMs?: number } = {},
): Promise<{ ok: boolean }> {
  const needed = 3;
  if (MOCK && !replayName()) {
    // Simulated pass so the mock UI flow runs; nothing is persisted, thresholds stay default.
    for (let done = 0; done <= needed; done++) {
      onProgress(done, needed);
      if (done < needed) await new Promise((r) => setTimeout(r, 300));
    }
    mockCalibrated = true;
    return { ok: true };
  }
  const base = { ...currentParams(), single: false };
  // Relaxed detection: half the thresholds, no gate, no cooldown, so weak nods still count.
  const relaxed: DetectorParams = { ...base, down: base.down / 2, up: base.up / 2, gate: Infinity, cooldownMs: 0 };
  const nods: NodInfo[] = [];
  let done = 0;
  const wasRunning = stopImu !== null || starting !== null;
  const restore = sink;
  const result = await new Promise<{ ok: boolean }>((resolve) => {
    const finish = (ok: boolean) => {
      clearTimeout(timer);
      resolve({ ok });
    };
    const timer = setTimeout(() => finish(false), opts.timeoutMs ?? 30000);
    const d = new Detector(relaxed, (n) => {
      nods.push(n);
      // The 3rd double nod's return lobe has ended: its amplitude is in.
      if (done >= needed && nods.length >= needed * 2) finish(true);
    });
    sink = (s) => {
      if (d.push(s) === 'NOD' && done < needed) onProgress(++done, needed);
    };
    onProgress(0, needed);
    void ensureImu().catch(() => finish(false));
  });
  sink = restore;
  if (!wasRunning) await stopHeadGestures();
  if (!result.ok) return result;
  const s = getSensitivity();
  // Persist unscaled values: the sensitivity slider applies on top at load time.
  const down = Math.min(DEFAULT_PARAMS.down, 0.6 * median(nods.map((n) => n.down)) * s);
  const up = Math.min(DEFAULT_PARAMS.up, 0.6 * median(nods.map((n) => n.up)) * s);
  if (down < 0.6 * DEFAULT_PARAMS.down || up < 0.6 * DEFAULT_PARAMS.up) {
    console.info('[motion] calibration: nods too weak, keeping defaults', { down, up });
    return { ok: false };
  }
  setDetectorOverrides({ ...(getDetectorOverrides() ?? {}), down, up, calibrated: true, calibratedAt: Date.now() });
  console.info('[motion] calibrated', { down: +down.toFixed(1), up: +up.toFixed(1) });
  if (listener) sink = liveSink(); // pick up the new thresholds
  return { ok: true };
}
