// Dev-only IMU recorder (?dev=1). Records {t, x, y, z} from the glasses and prints the
// fixture JSON on the phone-side page to copy off. Motion only: no audio, no names (the
// wearer is a letter), nothing sent to the relay. Fixtures land in app/tests/motion/fixtures/.
import { replayName, startImu, type ImuFixture, type ImuSample } from './imu.ts';
import { currentParams } from './gestures.ts';
import { MOCK, getImuPace, setImuPace } from '../settings.ts';

export const ACTIVITIES = ['still', 'double-nod', 'shake', 'bench-work', 'walking', 'talking-nodding'] as const;
const MAX_RECORD_SECONDS = 1800;

export async function record(seconds: number, meta: { activity: string; wearer: string }): Promise<ImuFixture> {
  if (!Number.isFinite(seconds) || seconds < 3 || seconds > MAX_RECORD_SECONDS) {
    throw new Error('Record between 3 and 1800 seconds.');
  }
  if (MOCK || replayName()) throw new Error('G2 recording requires live IMU input, without mock mode or replay.');
  const pace = getImuPace(), params = currentParams();
  const samples: ImuSample[] = [];
  const stop = await startImu((s) => samples.push(s), { fixedPace: true });
  await new Promise((r) => setTimeout(r, seconds * 1000));
  await stop();
  if (!samples.length) throw new Error('No G2 IMU samples received. Check the glasses connection.');
  const t0 = samples[0]?.t ?? 0;
  const r3 = (v: number) => Math.round(v * 1000) / 1000;
  return {
    meta: {
      source: 'g2',
      activity: meta.activity,
      wearer: meta.wearer.replace(/[^A-Z]/gi, '').slice(0, 1).toUpperCase() || 'A', // a letter, never a name
      pace,
      params,
      seconds,
      recorded_at: new Date().toISOString().slice(0, 10),
      summary: characterize(samples),
    },
    samples: samples.map((s) => [r3(s.t - t0), s.x, s.y, s.z]),
  };
}

const quantile = (xs: number[], q: number): number => {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(q * s.length))];
};

/** What the numbers say. The hint is a heuristic to check against the protocol, not a verdict. */
export function characterize(samples: ImuSample[]) {
  const n = samples.length;
  const dts = samples.slice(1).map((s, i) => s.t - samples[i].t);
  const seconds = n > 1 ? (samples[n - 1].t - samples[0].t) / 1000 : 0;
  const stats = (k: 'x' | 'y' | 'z') => {
    const v = samples.map((s) => s[k]);
    const mean = v.reduce((a, b) => a + b, 0) / (n || 1);
    const std = Math.sqrt(v.reduce((a, b) => a + (b - mean) ** 2, 0) / (n || 1));
    return {
      mean: +mean.toFixed(3), std: +std.toFixed(3),
      min: v.reduce((a, b) => Math.min(a, b), v[0] ?? 0),
      max: v.reduce((a, b) => Math.max(a, b), v[0] ?? 0),
    };
  };
  const axes = { x: stats('x'), y: stats('y'), z: stats('z') };
  const mags = samples.map((s) => Math.hypot(s.x, s.y, s.z));
  const magMean = mags.reduce((a, b) => a + b, 0) / (n || 1);
  const magStd = Math.sqrt(mags.reduce((a, b) => a + (b - magMean) ** 2, 0) / (n || 1));
  const dominant = (['x', 'y', 'z'] as const).reduce((a, b) => (axes[b].std > axes[a].std ? b : a));
  const steady = magStd < 0.05 * Math.max(magMean, 1e-9);
  const hint =
    steady && Math.abs(magMean - 9.81) < 1.5
      ? 'steady |v| ~ 9.8: accelerometer in m/s^2? (gravity)'
      : steady && Math.abs(magMean - 1) < 0.15
        ? 'steady |v| ~ 1: accelerometer in g? (gravity)'
        : Math.max(...(['x', 'y', 'z'] as const).map((k) => Math.abs(axes[k].mean))) < 3 * Math.max(axes.x.std, axes.y.std, axes.z.std, 1e-9)
          ? 'axes centred on 0: angular rate? check the still recording'
          : 'steady non-zero offsets: angles? check the range (+-180 deg / +-pi rad)';
  return {
    n,
    seconds: +seconds.toFixed(2),
    hz: seconds ? +((n - 1) / seconds).toFixed(1) : 0,
    dt_median_ms: +quantile(dts, 0.5).toFixed(1),
    dt_p95_ms: +quantile(dts, 0.95).toFixed(1),
    burst_frac: +(dts.filter((d) => d < 1).length / (dts.length || 1)).toFixed(3), // samples sharing an arrival time
    axes,
    magnitude: { mean: +magMean.toFixed(3), std: +magStd.toFixed(3) },
    dominant_axis: dominant,
    hint,
  };
}

/** The phone-side page. Part 1 mounts it behind ?dev=1 after the startup page exists. */
export function mountRecorder(root: HTMLElement): void {
  const box = document.createElement('section');
  box.innerHTML = `
    <h3>IMU recorder (dev)</h3>
    <fieldset>
    <label>pace <select id="imu-pace">${[100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
      .map((p) => `<option ${p === getImuPace() ? 'selected' : ''}>${p}</option>`)
      .join('')}</select></label>
    <label>activity <select id="imu-act">${ACTIVITIES.map((a) => `<option>${a}</option>`).join('')}</select></label>
    <label>wearer <input id="imu-wearer" value="A" size="1" maxlength="1"></label>
    <label>seconds <input id="imu-secs" type="number" value="30" min="3" max="${MAX_RECORD_SECONDS}"></label>
    <button id="imu-go">Record</button>
    </fieldset>
    <button id="imu-copy">Copy JSON</button>
    <pre id="imu-sum"></pre>
    <textarea id="imu-out" rows="6" style="width:100%" readonly></textarea>`;
  root.append(box);
  const $ = <T extends HTMLElement>(id: string) => box.querySelector<T>(`#${id}`)!;
  $('imu-go').addEventListener('click', async () => {
    const controls = box.querySelector('fieldset')!;
    controls.disabled = true;
    $<HTMLTextAreaElement>('imu-out').value = '';
    setImuPace(Number($<HTMLSelectElement>('imu-pace').value));
    const seconds = Number($<HTMLInputElement>('imu-secs').value);
    $('imu-sum').textContent = `recording ${seconds} s...`;
    try {
      const f = await record(seconds, { activity: $<HTMLSelectElement>('imu-act').value, wearer: $<HTMLInputElement>('imu-wearer').value });
      $('imu-sum').textContent = JSON.stringify(f.meta, null, 1);
      $<HTMLTextAreaElement>('imu-out').value = JSON.stringify(f);
    } catch (e) {
      $('imu-sum').textContent = `Recording failed: ${(e as Error).message}`;
    } finally {
      controls.disabled = false;
    }
  });
  $('imu-copy').addEventListener('click', () => {
    const out = $<HTMLTextAreaElement>('imu-out');
    out.select();
    void navigator.clipboard?.writeText(out.value).catch(() => document.execCommand('copy'));
  });
}
