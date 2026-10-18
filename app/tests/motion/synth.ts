// SYNTHETIC IMU fixtures - a stand-in until the G2 recordings exist. NOT hardware data.
// Run: node tests/motion/synth.ts   (Node >= 23.6 strips the types; output is deterministic)
//
// Model: head Euler angles in degrees (pitch on x, looking down negative; yaw on y; roll
// on z), sampled at 50 Hz with BLE-style arrival jitter and bursts. Movements are
// minimum-jerk ramps. Amplitudes and durations follow published head-kinematics ranges
// (deliberate nods 10-25 deg in 0.4-0.7 s; walking head pitch a few degrees at step
// rate). Whether the G2 reports angles, rates or acceleration is unknown until the
// characterisation; the detector takes that as a knob (DetectorParams.signal/scale).
import { writeFileSync } from 'node:fs';

const HZ = 50;
const OUT = new URL('./fixtures/', import.meta.url);

function rng(seed: number) {
  let a = seed >>> 0;
  const next = () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const uni = (lo: number, hi: number) => lo + (hi - lo) * next();
  const gauss = () => Math.sqrt(-2 * Math.log(next() || 1e-12)) * Math.cos(2 * Math.PI * next());
  return { next, uni, gauss };
}

type R = ReturnType<typeof rng>;
const minJerk = (s: number) => (s <= 0 ? 0 : s >= 1 ? 1 : s * s * s * (10 - 15 * s + 6 * s * s));

class Session {
  readonly n: number;
  readonly p: Float64Array;
  readonly y: Float64Array;
  readonly r: Float64Array;
  readonly seconds: number;
  readonly rand: R;
  constructor(seconds: number, rand: R) {
    this.seconds = seconds;
    this.rand = rand;
    this.n = Math.round(seconds * HZ);
    this.p = new Float64Array(this.n);
    this.y = new Float64Array(this.n);
    this.r = new Float64Array(this.n);
  }
  /** Add f(t) over [t0, t1) seconds to one axis; hold f(t1) afterwards when hold is set. */
  add(axis: 'p' | 'y' | 'r', t0: number, t1: number, f: (t: number) => number, hold = false): void {
    for (let i = Math.max(0, Math.floor(t0 * HZ)); i < this.n; i++) {
      const t = i / HZ;
      if (t >= t1 && !hold) break;
      this[axis][i] += f(Math.min(t, t1) - t0);
    }
  }
  /** Posture change: minimum-jerk ramp by delta over dur, then held. */
  move(axis: 'p' | 'y' | 'r', t0: number, dur: number, delta: number): void {
    this.add(axis, t0, t0 + dur, (t) => delta * minJerk(t / dur), true);
  }
  /** One deliberate nod: down by amp over td, back up over tu. Small yaw/roll crosstalk. */
  nod(t0: number, amp: number, td: number, tu: number): number {
    this.add('p', t0, t0 + td + tu, (t) => -amp * (t < td ? minJerk(t / td) : 1 - minJerk((t - td) / tu)));
    const k = this.rand.uni(-0.1, 0.1);
    this.add('y', t0, t0 + td + tu, (t) => k * amp * Math.sin((Math.PI * t) / (td + tu)));
    this.add('r', t0, t0 + td + tu, (t) => 0.5 * k * amp * Math.sin((Math.PI * t) / (td + tu)));
    return t0 + td + tu;
  }
  /** One shake: yaw sinusoid under a Hann window, ~1.5 cycles. Small pitch crosstalk. */
  shake(t0: number, amp: number, f: number, cycles: number): number {
    const dur = cycles / f;
    const hann = (t: number) => Math.sin((Math.PI * t) / dur) ** 2;
    this.add('y', t0, t0 + dur, (t) => amp * hann(t) * Math.sin(2 * Math.PI * f * t));
    const k = this.rand.uni(0.03, 0.1);
    this.add('p', t0, t0 + dur, (t) => -k * amp * hann(t));
    return t0 + dur;
  }
  /** Slow working micro-motion while holding a posture. */
  fidget(t0: number, t1: number, amp: number): void {
    const fp = this.rand.uni(0.2, 0.6);
    const fy = this.rand.uni(0.2, 0.6);
    const ph = this.rand.uni(0, 6.28);
    this.add('p', t0, t1, (t) => amp * Math.sin(2 * Math.PI * fp * t + ph) * Math.min(1, t, t1 - t0 - t));
    this.add('y', t0, t1, (t) => 1.5 * amp * Math.sin(2 * Math.PI * fy * t + ph) * Math.min(1, t, t1 - t0 - t));
  }
  rows(): [number, number, number, number][] {
    const { gauss, next } = this.rand;
    const drift = [0, 0, 0];
    const out: [number, number, number, number][] = [];
    let last = 0;
    for (let i = 0; i < this.n; i++) {
      for (let k = 0; k < 3; k++) drift[k] += 0.004 * gauss();
      // BLE arrival: +-2 ms jitter, and 3 % of samples arrive in the same burst as the previous one.
      let t = (i * 1000) / HZ + 2 * gauss();
      if (i && next() < 0.03) t = last;
      t = Math.max(t, last);
      last = t;
      const r2 = (v: number) => Math.round(v * 100) / 100;
      out.push([r2(t), r2(this.p[i] + drift[0] + 0.15 * gauss()), r2(this.y[i] + drift[1] + 0.15 * gauss()), r2(this.r[i] + drift[2] + 0.15 * gauss())]);
    }
    return out;
  }
}

function write(activity: string, s: Session, extra: Record<string, unknown>): void {
  const fixture = {
    meta: {
      source: 'synthetic',
      activity,
      hz: HZ,
      seconds: s.seconds,
      model: 'Euler angles in degrees; pitch=x (down negative), yaw=y, roll=z',
      generator: 'tests/motion/synth.ts',
      ...extra,
    },
    samples: s.rows(),
  };
  writeFileSync(new URL(`${activity}.synthetic.json`, OUT), JSON.stringify(fixture));
  console.log(`${activity}.synthetic.json: ${fixture.samples.length} samples`, extra);
}

// still: 30 s, glasses on a still head
{
  const s = new Session(30, rng(1));
  s.fidget(0, 30, 0.4);
  write('still', s, { expect: { NOD: 0, SHAKE: 0 } });
}

// double-nod: 10 deliberate double nods, 2.5-4 s apart
{
  const R = rng(2);
  const s = new Session(45, R);
  let t = 2;
  for (let i = 0; i < 10; i++) {
    const amp = R.uni(12, 22);
    const end = s.nod(t, amp, R.uni(0.2, 0.3), R.uni(0.22, 0.38));
    s.nod(end + R.uni(0.06, 0.25), amp * R.uni(0.8, 1.1), R.uni(0.2, 0.3), R.uni(0.22, 0.38));
    s.fidget(t + 1.6, t + 3.4, 0.5);
    t += R.uni(3.5, 4.2);
  }
  write('double-nod', s, { expect: { NOD: 10, SHAKE: 0 } });
}

// shake: 10 head shakes, 2.5-4 s apart
{
  const R = rng(3);
  const s = new Session(42, R);
  let t = 2;
  for (let i = 0; i < 10; i++) {
    s.shake(t, R.uni(15, 28), R.uni(2, 2.6), R.uni(1.5, 2));
    t += R.uni(3.4, 4);
  }
  write('shake', s, { expect: { NOD: 0, SHAKE: 10 } });
}

// bench-work: 2 min script - look down at the bench, up at a shelf, turn to a toolbox,
// read a gauge, quick single glances (the hard negative), talk to a coworker.
{
  const R = rng(4);
  const s = new Session(120, R);
  let t = 1;
  const actions = ['bench', 'shelf', 'toolbox', 'gauge', 'glance', 'coworker'] as const;
  const counts: Record<string, number> = {};
  while (t < 112) {
    const a = actions[Math.floor(R.next() * actions.length)];
    counts[a] = (counts[a] ?? 0) + 1;
    if (a === 'bench') {
      const d = R.uni(25, 45), down = R.uni(0.6, 1.1), hold = R.uni(2, 6);
      s.move('p', t, down, -d);
      s.fidget(t + down, t + down + hold, 2);
      s.move('p', t + down + hold, R.uni(0.6, 1.1), d);
      t += down + hold + 1.2;
    } else if (a === 'shelf') {
      const d = R.uni(20, 35), dur = R.uni(0.8, 1.2), hold = R.uni(1.5, 3);
      s.move('p', t, dur, d);
      s.move('p', t + dur + hold, dur, -d);
      t += 2 * dur + hold;
    } else if (a === 'toolbox') {
      const d = R.uni(60, 90) * (R.next() < 0.5 ? -1 : 1), dur = R.uni(0.8, 1.4), hold = R.uni(1.5, 3);
      s.move('y', t, dur, d);
      s.move('p', t + 0.2, dur, -15);
      s.move('p', t + dur + hold, dur, 15);
      s.move('y', t + dur + hold, dur, -d);
      t += 2 * dur + hold + 0.3;
    } else if (a === 'gauge') {
      const d = R.uni(10, 18), dur = R.uni(0.3, 0.4), hold = R.uni(0.8, 1.5);
      s.move('p', t, dur, -d);
      s.move('p', t + dur + hold, dur, d);
      t += 2 * dur + hold;
    } else if (a === 'glance') {
      // A quick look down and back: one nod-shaped movement, never two within 1.2 s.
      const d = R.uni(12, 20), dur = R.uni(0.25, 0.3), hold = R.uni(0.1, 0.25);
      s.move('p', t, dur, -d);
      s.move('p', t + dur + hold, R.uni(0.25, 0.35), d);
      t += 1.5;
    } else {
      const d = R.uni(25, 40) * (R.next() < 0.5 ? -1 : 1), dur = R.uni(0.5, 0.8), hold = R.uni(1.5, 4);
      s.move('y', t, dur, d);
      s.move('y', t + dur + hold, dur, -d);
      t += 2 * dur + hold;
    }
    t += R.uni(0.8, 2.5);
  }
  write('bench-work', s, { expect: { NOD: 0, SHAKE: 0 }, script: counts });
}

// walking: 1 min - step-rate head bob, stride-rate sway, two turns, a look at the floor
{
  const R = rng(5);
  const s = new Session(60, R);
  const fs = R.uni(1.8, 2.0);
  s.add('p', 0, 60, (t) => 3.5 * Math.sin(2 * Math.PI * fs * t) + 0.8 * Math.sin(4 * Math.PI * fs * t + 1));
  s.add('y', 0, 60, (t) => 4 * Math.sin(Math.PI * fs * t));
  s.add('r', 0, 60, (t) => 3 * Math.sin(Math.PI * fs * t + 0.5));
  for (let k = 0; k < 120; k++) {
    const t0 = k / fs + R.uni(-0.02, 0.02); // heel strike: a short jolt
    s.add('p', t0, t0 + 0.08, (t) => -1.2 * Math.sin((Math.PI * t) / 0.08));
  }
  s.move('y', 18, 2, 90);
  s.move('y', 41, 2.2, -90);
  s.move('p', 28, 0.8, -30);
  s.move('p', 31, 0.8, 30);
  write('walking', s, { expect: { NOD: 0, SHAKE: 0 } });
}

// talking-nodding: 30 s of small conversational nods while speaking. Documented, not asserted.
{
  const R = rng(6);
  const s = new Session(30, R);
  let t = 1;
  while (t < 29) {
    s.nod(t, R.uni(4, 9), R.uni(0.15, 0.25), R.uni(0.15, 0.25));
    t += R.uni(0.6, 1.4);
  }
  s.fidget(0, 30, 1.5);
  write('talking-nodding', s, { expect: 'document' });
}
