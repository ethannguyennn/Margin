import { getDevice, RELAY_ORIGIN } from '../settings';
import type { FeedRequest } from './live-feed';
/** Tokens stay in headers, never URLs, DOM or logs. */
export const deviceFeedRequest: FeedRequest = async <T>(path: string, init: RequestInit = {}): Promise<T> => {
  const device = getDevice();
  if (!device) throw new Error('Join the same workspace as your glasses to view their display.');
  const headers = new Headers(init.headers); headers.set('Authorization', `Bearer ${device.device_token}`);
  // The glasses WebView may predate AbortSignal.any/timeout.
  const abort = new AbortController(), cancel = () => abort.abort();
  if (init.signal?.aborted) cancel();
  init.signal?.addEventListener('abort', cancel, { once: true });
  const timer = setTimeout(cancel, 6000);
  try {
    const response = await fetch(RELAY_ORIGIN + path, { ...init, headers, cache: 'no-store', signal: abort.signal });
    if (!response.ok) throw Object.assign(new Error(response.status === 401 ?
      'Join the same workspace as your glasses to view their display.' : 'Display feed unavailable. Retrying.'), { status: response.status });
    return await response.json() as T;
  } finally { clearTimeout(timer); init.signal?.removeEventListener('abort', cancel); }
};
