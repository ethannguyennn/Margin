import { getDevice, RELAY_ORIGIN } from '../settings';
import type { FeedRequest } from './live-feed';
/** Tokens stay in headers, never URLs, DOM or logs. */
export const deviceFeedRequest: FeedRequest = async <T>(path: string, init: RequestInit = {}): Promise<T> => {
  const device = getDevice();
  if (!device) throw new Error('Join the same workspace as your glasses to view their display.');
  const headers = new Headers(init.headers); headers.set('Authorization', `Bearer ${device.device_token}`);
  const response = await fetch(RELAY_ORIGIN + path, { ...init, headers, cache: 'no-store',
    signal: init.signal ? AbortSignal.any([init.signal, AbortSignal.timeout(6000)]) : AbortSignal.timeout(6000) });
  if (!response.ok) throw Object.assign(new Error(response.status === 401 ?
    'Join the same workspace as your glasses to view their display.' : 'Display feed unavailable. Retrying.'), { status: response.status });
  return response.json() as Promise<T>;
};
