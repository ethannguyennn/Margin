// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { DisplayPublisher, type DisplayFrame, type FeedRequest } from '../src/simulator/live-feed';
import { mountLiveViewer } from '../src/simulator/live-viewer';
import { LensDisplay } from '../src/ui/layout';

afterEach(() => { vi.useRealTimers(); document.body.replaceChildren(); });
const frame = (main: string): DisplayFrame => ({ screen: 'STEP', frame: { header: '1/3', main, footer: 'next' } });
const flush = () => vi.advanceTimersByTimeAsync(500);

it('publishes only acknowledged hardware text, coalesces updates, heartbeats and pauses', async () => {
  vi.useFakeTimers();
  const updates: any[] = [];
  const request: FeedRequest = vi.fn(async (path, init) => {
    if (path.endsWith('/stream')) return { stream_id: 'stream' } as any;
    updates.push(JSON.parse(init!.body as string)); return {} as any;
  });
  const publisher = new DisplayPublisher(request);
  await flush(); expect(request).not.toHaveBeenCalled();
  let allow = true;
  const hardware = new LensDisplay({ createStartUpPageContainer: async () => 0, textContainerUpgrade: async () => allow });
  const render = async (next: DisplayFrame) => {
    await hardware.render(next.frame);
    publisher.acknowledged({ screen: next.screen, frame: hardware.acknowledgedFrame! });
  };
  await render(frame('first')); await render(frame('latest')); await flush();
  expect(updates).toHaveLength(1); expect(updates[0].frame.main).toBe('latest');
  allow = false; await expect(render(frame('rejected'))).rejects.toThrow();
  await vi.advanceTimersByTimeAsync(3000);
  expect(updates.at(-1).frame.main).toBe('latest'); expect(updates.at(-1).sequence).toBe(2);
  publisher.setActive(false); await flush(); expect(updates.at(-1).connected).toBe(false);
  const count = updates.length; await vi.advanceTimersByTimeAsync(10000); expect(updates).toHaveLength(count);
  publisher.dispose();
});

it('serializes network sends, reopens after relay restart and stops for a newer stream', async () => {
  vi.useFakeTimers(); let release!: () => void, streams = 0, failure = 0;
  const request: FeedRequest = vi.fn(async (path) => {
    if (path.endsWith('/stream')) { streams++; return { stream_id: 's' + streams } as any; }
    if (failure) throw { status: failure };
    await new Promise<void>(resolve => { release = resolve; }); return {} as any;
  });
  const publisher = new DisplayPublisher(request); publisher.acknowledged(frame('one'));
  await flush(); publisher.acknowledged(frame('two'));
  await vi.advanceTimersByTimeAsync(4000); expect(request).toHaveBeenCalledTimes(2);
  release(); await Promise.resolve(); failure = 410; await flush();
  failure = 409; await flush(); expect(streams).toBe(2);
  const count = vi.mocked(request).mock.calls.length;
  await vi.advanceTimersByTimeAsync(10000); expect(request).toHaveBeenCalledTimes(count);
  publisher.dispose();
});

it('aborts the publisher when the host app exits', async () => {
  vi.useFakeTimers(); let signal: AbortSignal | undefined;
  const publisher = new DisplayPublisher(async (_path, init) => {
    signal = init?.signal as AbortSignal;
    await new Promise<void>(() => {}); return {} as any;
  });
  publisher.acknowledged(frame('text')); await flush(); publisher.dispose();
  expect(signal?.aborted).toBe(true);
});

it('renders the selected remote device, updates without controls and labels stale frames', async () => {
  vi.useFakeTimers(); let main = 'Tighten to 4 N-m', live = true, sequence = 1;
  const host = document.createElement('div'); document.body.append(host);
  const request: FeedRequest = vi.fn(async path => path.endsWith('/displays') ? [
    { device_id: 'g2', worker_name: 'Bay 3', live: true }, { device_id: 'other', worker_name: 'Bay 4', live: false },
  ] as any : ({ device_id: 'g2', live, last_seen: 1000, sequence, ...frame(main) }) as any);
  const viewer = mountLiveViewer(host, request); await vi.advanceTimersByTimeAsync(0);
  expect(host.textContent).toContain('Live from glasses'); expect(host.querySelector('[role="img"]')?.textContent).toContain(main);
  expect(host.querySelector('button')).toBeNull();
  main = 'Next step'; sequence++; live = false; await vi.advanceTimersByTimeAsync(1000);
  expect(host.textContent).toContain('Offline or paused'); expect(host.querySelector('[role="img"]')?.textContent).toContain(main);
  const select = host.querySelector('select')!; select.value = 'other'; select.dispatchEvent(new Event('change'));
  expect(host.querySelector('[role="img"]')?.textContent).not.toContain(main);
  viewer.dispose(); expect(host.children).toHaveLength(0);
});

it('ignores responses for a previously selected device and clears on network failure', async () => {
  vi.useFakeTimers(); const host = document.createElement('div');
  let resolve!: (value: unknown) => void, fail = false;
  const request: FeedRequest = vi.fn(async path => {
    if (fail) throw new Error('Connection lost');
    if (path.endsWith('/displays')) return [{ device_id: 'one' }, { device_id: 'two' }] as any;
    return await new Promise(r => { resolve = r; }) as any;
  });
  const viewer = mountLiveViewer(host, request); await vi.advanceTimersByTimeAsync(0);
  const select = host.querySelector('select')!; select.value = 'two'; select.dispatchEvent(new Event('change'));
  resolve({ live: true, ...frame('PRIVATE OLD FRAME'), sequence: 1 });
  await vi.advanceTimersByTimeAsync(0); expect(host.textContent).not.toContain('PRIVATE OLD FRAME');
  fail = true; await vi.advanceTimersByTimeAsync(1000);
  expect(host.textContent).toContain('Connection lost'); expect(host.querySelector('[data-live="true"]')).toBeNull();
  viewer.dispose();
});

it('acknowledges reference fallback without claiming the failed image is displayed', async () => {
  const display = new LensDisplay({ createStartUpPageContainer: async () => 0,
    rebuildPageContainer: async () => true, textContainerUpgrade: async () => true,
    updateImageRawData: async () => 'sendFailed' as never }, async () => new Uint8Array());
  await display.render({ header: 'SPECS', main: 'Instructions', footer: '', graphic_id: 'image' });
  expect(display.acknowledgedFrame).toEqual({ header: 'SPECS', main: 'Instructions', footer: '', graphic_id: undefined });
});
