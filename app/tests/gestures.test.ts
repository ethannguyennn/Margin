// Run: npm test
// Every fixture in tests/motion/fixtures/ runs through detect() against its meta.expect.
// *.synthetic.json are modelled data (tests/motion/synth.ts); G2 recordings from
// motion/record.ts drop in beside them and are picked up automatically.
import { test } from 'vitest';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';

process.env.VITE_MOCK = '0';

const { detect, DEFAULT_PARAMS, Detector, currentParams } = await import('../src/motion/gestures.ts');
const { fixtureSamples, toSample } = await import('../src/motion/imu.ts');
type Fixture = import('../src/motion/imu.ts').ImuFixture;
type Sample = import('../src/motion/imu.ts').ImuSample;
type Params = import('../src/motion/gestures.ts').DetectorParams;

const DIR = new URL('./motion/fixtures/', import.meta.url);
const files = readdirSync(DIR).filter((f) => f.endsWith('.json'));
const load = (f: string): Fixture => JSON.parse(readFileSync(new URL(f, DIR), 'utf8'));
const paramsFor = (fx: Fixture): Params => ({ ...DEFAULT_PARAMS, ...((fx.meta.params as Partial<Params>) ?? {}) });
const count = (events: { g: string }[], g: string) => events.filter((e) => e.g === g).length;

/** The results table for docs/handoffs/PART-2.md. */
const table: string[] = [];

for (const f of files) {
  test(`fixture ${f}`, () => {
    const fx = load(f);
    const events = detect(fixtureSamples(fx), paramsFor(fx));
    const got = { NOD: count(events, 'NOD'), SHAKE: count(events, 'SHAKE') };
    table.push(`${f}: NOD=${got.NOD} SHAKE=${got.SHAKE} expect=${JSON.stringify(fx.meta.expect)} source=${fx.meta.source}`);
    if (typeof fx.meta.expect === 'object' && fx.meta.expect) assert.deepEqual(got, fx.meta.expect, `${f}: ${JSON.stringify(events)}`);
  });
}

test('results table', () => {
  console.info(['[gestures] detect() over fixtures:', ...table].join('\n  '));
  assert.ok(files.length >= 6);
});

const nods = fixtureSamples(load('double-nod.synthetic.json'));

test('signal "rate": the same nods as angular rate detect the same 10 double nods', () => {
  const rate: Sample[] = nods.map((s, i) => {
    if (i === 0) return { ...s, x: 0, y: 0, z: 0 };
    const p = nods[i - 1];
    const dt = Math.max(s.t - p.t, 20) / 1000; // a gyro reports rate even inside a BLE burst
    return { t: s.t, x: (s.x - p.x) / dt, y: (s.y - p.y) / dt, z: (s.z - p.z) / dt };
  });
  assert.equal(count(detect(rate, { ...DEFAULT_PARAMS, signal: 'rate' }), 'NOD'), 10);
});

test('scale: radians with scale 180/pi detect the same', () => {
  const rad = nods.map((s) => ({ t: s.t, x: (s.x * Math.PI) / 180, y: (s.y * Math.PI) / 180, z: (s.z * Math.PI) / 180 }));
  assert.equal(count(detect(rad, { ...DEFAULT_PARAMS, scale: 180 / Math.PI }), 'NOD'), 10);
  assert.equal(count(detect(rad, DEFAULT_PARAMS), 'NOD'), 0, 'wrong units must not trigger');
});

test('axis mapping and sign are knobs: swapped axes with matching params detect the same', () => {
  const swapped = nods.map((s) => ({ t: s.t, x: s.z, y: s.y, z: -s.x }));
  assert.equal(count(detect(swapped, { ...DEFAULT_PARAMS, pitchAxis: 'z', pitchSign: -1 }), 'NOD'), 10);
});

test('angle wrap: pitch near +-180 deg does not spike the rate', () => {
  const near = nods.map((s) => {
    let x = s.x + 179;
    if (x > 180) x -= 360;
    return { ...s, x };
  });
  assert.equal(count(detect(near, DEFAULT_PARAMS), 'NOD'), 10);
});

test('sample rate: 25 Hz still resolves every double nod (half the synthetic rate)', () => {
  const half = nods.filter((_, i) => i % 2 === 0);
  assert.equal(count(detect(half, DEFAULT_PARAMS), 'NOD'), 10);
  const quarter = nods.filter((_, i) => i % 4 === 0);
  console.info(`[gestures] 12.5 Hz: ${count(detect(quarter, DEFAULT_PARAMS), 'NOD')}/10 double nods`);
});

/** A synthetic pitch trace at 50 Hz: angles in degrees from a function of t (s). */
function trace(seconds: number, pitch: (t: number) => number, yaw: (t: number) => number = () => 0): Sample[] {
  return Array.from({ length: seconds * 50 }, (_, i) => ({ t: i * 20, x: pitch(i / 50), y: yaw(i / 50), z: 0 }));
}
const bump = (t: number, t0: number, amp: number, dur = 0.5) =>
  t >= t0 && t <= t0 + dur ? -amp * Math.sin((Math.PI * (t - t0)) / dur) ** 2 : 0;
const double = (t0: number) => (t: number) => bump(t, t0, 15) + bump(t, t0 + 0.65, 15);

test('cooldown: a double nod 1 s after a double nod is ignored, 2.5 s after is not', () => {
  const close = trace(5, (t) => double(0.5)(t) + double(1.9)(t));
  assert.equal(count(detect(close, DEFAULT_PARAMS), 'NOD'), 1);
  const far = trace(6, (t) => double(0.5)(t) + double(3.2)(t));
  assert.equal(count(detect(far, DEFAULT_PARAMS), 'NOD'), 2);
});

test('motion gate: a double nod during sustained head motion is suppressed', () => {
  const calm = trace(4, double(1.5));
  assert.equal(count(detect(calm, DEFAULT_PARAMS), 'NOD'), 1);
  const busy = trace(4, double(1.5), (t) => 12 * Math.sin(2 * Math.PI * 1.2 * t)); // whole-body turning
  assert.equal(count(detect(busy, DEFAULT_PARAMS), 'NOD'), 0);
});

test('single nod: off by default (one nod = nothing), on in single mode', () => {
  const one = trace(3, (t) => bump(t, 1, 15));
  assert.equal(count(detect(one, DEFAULT_PARAMS), 'NOD'), 0);
  assert.equal(count(detect(one, { ...DEFAULT_PARAMS, single: true }), 'NOD'), 1);
});

test('two nods too far apart are not a double nod', () => {
  const apart = trace(4, (t) => bump(t, 0.5, 15) + bump(t, 2.2, 15));
  assert.equal(count(detect(apart, DEFAULT_PARAMS), 'NOD'), 0);
});

test('a single left-right turn is not a shake; left-right-left is', () => {
  // Turn to one side and back: 2 rate lobes, 1 reversal.
  const turn = trace(3, () => 0, (t) => (t > 1 && t < 1.6 ? 30 * Math.sin((Math.PI * (t - 1)) / 0.6) ** 2 : 0));
  assert.equal(count(detect(turn, DEFAULT_PARAMS), 'SHAKE'), 0);
  // One full left-right cycle: 3 rate lobes, 2 reversals.
  const shake = trace(3, () => 0, (t) => (t > 1 && t < 1.5 ? 25 * Math.sin((2 * Math.PI * (t - 1)) / 0.5) : 0));
  assert.equal(count(detect(shake, DEFAULT_PARAMS), 'SHAKE'), 1);
});

test('bursts and gaps: duplicate timestamps are tolerated, a long gap resets', () => {
  const burst = nods.map((s, i) => (i % 5 === 1 ? { ...s, t: nods[i - 1].t } : s));
  assert.equal(count(detect(burst, DEFAULT_PARAMS), 'NOD'), 10);
  const d = new Detector(DEFAULT_PARAMS);
  assert.equal(d.push({ t: 0, x: 0, y: 0, z: 0 }), null);
  assert.equal(d.push({ t: 5000, x: 90, y: 0, z: 0 }), null, 'a gap must not read as a 90 deg jump');
});

test('toSample: protobuf-omitted axes are 0; garbage is dropped', () => {
  assert.deepEqual(toSample({ x: 1.5 }, 10), { t: 10, x: 1.5, y: 0, z: 0 });
  assert.deepEqual(toSample({ x: '2', y: 3, z: null }, 5), { t: 5, x: 2, y: 3, z: 0 });
  assert.equal(toSample({ x: 'abc' }, 0), null);
  assert.equal(toSample(undefined, 0), null);
});

test('sensitivity and nod mode come from settings', () => {
  const store: Record<string, string> = {};
  (globalThis as any).localStorage = {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => (store[k] = v),
    removeItem: (k: string) => delete store[k],
  };
  store['margin.sensitivity'] = '2';
  store['margin.nodMode'] = '"single"';
  store['margin.detector'] = JSON.stringify({ down: 70, gate: 'junk' });
  const p = currentParams();
  assert.equal(p.down, 35, 'override 70 / sensitivity 2');
  assert.equal(p.up, DEFAULT_PARAMS.up / 2);
  assert.equal(p.gate, DEFAULT_PARAMS.gate, 'a wrongly typed override is ignored');
  assert.equal(p.single, true);
  delete (globalThis as any).localStorage;
});

// --- the stateful wrapper, over a fake bridge -----------------------------------
const { setBridge } = await import('../src/audio/capture.ts');
const g = await import('../src/motion/gestures.ts');

function imuBridge(answers = true) {
  const calls: Array<[boolean, number | undefined]> = [];
  let cb: ((e: any) => void) | null = null;
  setBridge({
    audioControl: async () => true,
    imuControl: async (open: boolean, pace?: number) => {
      calls.push([open, pace]);
      return answers ? true : new Promise<boolean>(() => {}); // the simulator never answers
    },
    onEvenHubEvent: (fn: (e: any) => void) => {
      cb = fn;
      return () => (cb = null);
    },
  });
  let clock = 0;
  Object.defineProperty(globalThis, 'performance', { value: { now: () => clock }, configurable: true, writable: true });
  return {
    calls,
    get subscribed() {
      return cb !== null;
    },
    sys: (eventType: number) => cb?.({ sysEvent: { eventType } }),
    /** Deliver samples as IMU_DATA_REPORT events at their own timestamps. */
    feed(samples: Sample[]) {
      for (const s of samples) {
        clock = s.t;
        cb?.({ sysEvent: { eventType: 8, imuData: { x: s.x, y: s.y, z: s.z } } });
      }
    },
  };
}
const settle = async () => {
  for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0));
};
const shifted = (samples: Sample[], dt: number) => samples.map((s) => ({ ...s, t: s.t + dt }));

test('live: IMU on at start, gestures delivered, IMU off on foreground exit, back on enter, off at stop', async () => {
  const hw = imuBridge();
  const got: string[] = [];
  await g.startHeadGestures((x) => got.push(x));
  assert.deepEqual(hw.calls, [[true, 500]], 'imuControl(true, P500) once');
  hw.feed(trace(4, double(1.5)));
  assert.deepEqual(got, ['NOD']);
  hw.sys(5); // FOREGROUND_EXIT_EVENT
  await settle();
  assert.deepEqual(hw.calls.at(-1), [false, undefined], 'IMU off in the background');
  hw.feed(shifted(trace(4, double(1.5)), 10000));
  assert.deepEqual(got, ['NOD'], 'no samples count while backgrounded');
  hw.sys(4); // FOREGROUND_ENTER_EVENT
  await settle();
  assert.deepEqual(hw.calls.at(-1), [true, 500]);
  g.simulateGesture('SHAKE');
  assert.deepEqual(got, ['NOD', 'SHAKE']);
  await g.stopHeadGestures();
  assert.deepEqual(hw.calls.at(-1), [false, undefined]);
  assert.equal(hw.subscribed, false);
});

test('live: an imuControl that never answers (simulator) times out instead of hanging', async () => {
  imuBridge(false);
  const t0 = Date.now();
  await g.startHeadGestures(() => {});
  assert.ok(Date.now() - t0 < 2500);
  await g.stopHeadGestures();
}, 8000);

/** n double nods of a given amplitude, 3 s apart, then 1 s of stillness. */
const nodSession = (amp: number, n = 3) =>
  trace(3 * n + 1, (t) => [...Array(n)].reduce((acc, _, i) => acc + bump(t, 1 + 3 * i, amp) + bump(t, 1.65 + 3 * i, amp), 0));

test('calibrate: 3 double nods set down/up to 60 % of the median peak and persist', async () => {
  const store: Record<string, string> = {};
  (globalThis as any).localStorage = {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => (store[k] = v),
    removeItem: (k: string) => delete store[k],
  };
  const hw = imuBridge();
  const progress: number[] = [];
  assert.equal(g.isCalibrated(), false);
  const p = g.calibrate((done) => progress.push(done), { timeoutMs: 3000 });
  await settle();
  hw.feed(shifted(nodSession(20), 50000));
  assert.deepEqual(await p, { ok: true });
  assert.deepEqual(progress, [0, 1, 2, 3]);
  assert.equal(g.isCalibrated(), true);
  const saved = JSON.parse(store['margin.detector']);
  assert.ok(saved.down > DEFAULT_PARAMS.down && saved.down < 100, `down=${saved.down}`);
  assert.deepEqual(hw.calls.at(-1), [false, undefined], 'calibration started the IMU, so it stops it');

  // Weak nods: detected by the relaxed pass, but below the floor -> defaults kept, ok: false.
  delete store['margin.detector'];
  const weak = g.calibrate(() => {}, { timeoutMs: 3000 });
  await settle();
  hw.feed(shifted(nodSession(7), 90000));
  assert.deepEqual(await weak, { ok: false });
  assert.equal(store['margin.detector'], undefined);
  delete (globalThis as any).localStorage;
});
