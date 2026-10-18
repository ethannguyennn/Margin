// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import { setDevice } from '../src/settings';
import { deviceFeedRequest } from '../src/simulator/device-feed';
afterEach(() => { setDevice(null); vi.unstubAllGlobals(); vi.useRealTimers(); });

it('requires workspace credentials and transmits the token only in headers', async () => {
  const fetcher = vi.fn(async () => new Response(JSON.stringify([]), { status: 200 })); vi.stubGlobal('fetch', fetcher);
  await expect(deviceFeedRequest('/v1/lens/displays')).rejects.toThrow('Join the same workspace');
  expect(fetcher).not.toHaveBeenCalled();
  setDevice({ device_id: 'test', device_token: 'test-private-token' });
  await deviceFeedRequest('/v1/lens/displays');
  const [url, options] = (fetcher.mock.calls as unknown as [string, RequestInit][])[0];
  expect(url).not.toContain('test-private-token');
  expect(new Headers(options.headers).get('Authorization')).toBe('Bearer test-private-token');
  expect(options.cache).toBe('no-store');
});

it('times out and forwards disposal with basic AbortController APIs', async () => {
  vi.useFakeTimers(); setDevice({ device_id: 'test', device_token: 'token' });
  let signal: AbortSignal | undefined;
  vi.stubGlobal('fetch', vi.fn(async (_url, init) => {
    signal = init.signal;
    return new Promise<Response>((_resolve, reject) => signal!.addEventListener('abort', () => reject(new Error('Aborted'))));
  }));
  const parent = new AbortController();
  const first = deviceFeedRequest('/v1/lens/displays', { signal: parent.signal }).catch(e => e);
  parent.abort(); expect(signal!.aborted).toBe(true); await first;
  const second = deviceFeedRequest('/v1/lens/displays').catch(e => e);
  await vi.advanceTimersByTimeAsync(6000); expect(signal!.aborted).toBe(true); await second;
});
