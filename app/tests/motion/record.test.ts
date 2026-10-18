// @vitest-environment jsdom
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

process.env.VITE_MOCK = '0';
const imu = await import('../../src/motion/imu.ts');
const { characterize, record, mountRecorder } = await import('../../src/motion/record.ts');

const stop = vi.fn(async () => {});

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(imu, 'startImu').mockImplementation(async (onSample) => {
    onSample({ t: 1000, x: 0, y: 0, z: 1 });
    onSample({ t: 1020, x: 0.1, y: 0, z: 0.99 });
    return stop;
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  stop.mockClear();
  document.body.replaceChildren();
  history.replaceState(null, '', '/');
  localStorage.clear();
});

test('a 30-minute recording holds its pace and saves motion, parameters and a wearer letter', async () => {
  const pending = record(1800, { activity: 'bench-work', wearer: 'Alice' });
  await vi.advanceTimersByTimeAsync(1800 * 1000);
  const fx = await pending;
  expect(imu.startImu).toHaveBeenCalledWith(expect.any(Function), { fixedPace: true });
  expect(stop).toHaveBeenCalledOnce();
  expect(fx.meta).toMatchObject({ source: 'g2', wearer: 'A', seconds: 1800, pace: 500 });
  expect(fx.meta.params).toHaveProperty('signal', 'auto');
  expect(fx.samples).toEqual([[0, 0, 0, 1], [20, 0.1, 0, 0.99]]);
  expect(JSON.stringify(fx)).not.toContain('Alice');
});

test.each([NaN, Infinity, -1, 0, 2, 1801])('rejects invalid recording length %s before opening IMU', async (seconds) => {
  await expect(record(seconds, { activity: 'still', wearer: 'A' })).rejects.toThrow('between 3 and 1800');
  expect(imu.startImu).not.toHaveBeenCalled();
});

test('replay cannot be labelled as a real G2 fixture', async () => {
  history.replaceState(null, '', '/?imu=double-nod');
  await expect(record(3, { activity: 'double-nod', wearer: 'A' })).rejects.toThrow('live IMU');
  expect(imu.startImu).not.toHaveBeenCalled();
});

test('an empty recording fails instead of exporting a hardware fixture', async () => {
  vi.mocked(imu.startImu).mockResolvedValue(stop);
  const pending = expect(record(3, { activity: 'still', wearer: 'A' })).rejects.toThrow('No G2 IMU samples');
  await vi.advanceTimersByTimeAsync(3000);
  await pending;
  expect(stop).toHaveBeenCalledOnce();
});

test('summary handles 30 minutes at 100 samples/s without spreading a large array', () => {
  const samples = Array.from({ length: 180001 }, (_, i) => ({ t: i * 10, x: i % 3, y: 0, z: 1 }));
  const summary = characterize(samples);
  expect(summary).toMatchObject({ n: 180001, seconds: 1800, hz: 100 });
  expect(summary.axes.x).toMatchObject({ min: 0, max: 2 });
  expect(characterize([]).axes.x).toEqual({ mean: 0, std: 0, min: 0, max: 0 });
});

test('recorder prevents overlapping runs and shows a recoverable failure', async () => {
  vi.mocked(imu.startImu).mockResolvedValue(stop);
  mountRecorder(document.body);
  const duration = document.querySelector<HTMLInputElement>('#imu-secs')!;
  expect(duration.max).toBe('1800');
  duration.value = '3';
  const output = document.querySelector<HTMLTextAreaElement>('#imu-out')!;
  output.value = 'old fixture';
  const go = document.querySelector<HTMLButtonElement>('#imu-go')!;
  go.click();
  go.click();
  expect(document.querySelector<HTMLFieldSetElement>('fieldset')!.disabled).toBe(true);
  expect(output.value).toBe('');
  await vi.advanceTimersByTimeAsync(3000);
  expect(imu.startImu).toHaveBeenCalledOnce();
  expect(document.querySelector('#imu-sum')!.textContent).toContain('No G2 IMU samples');
  expect(document.querySelector<HTMLFieldSetElement>('fieldset')!.disabled).toBe(false);
});
