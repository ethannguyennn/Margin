export const TOKEN_KEY = 'specs.portal.token';

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

function reasons(value: unknown): string {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(reasons).filter(Boolean).join('\n');
  if (value && typeof value === 'object') {
    const data = value as Record<string, unknown>;
    if (data.detail) return reasons(data.detail);
    if (data.reason) return `${data.label ? `Step ${data.label}: ` : ''}${reasons(data.reason)}`;
    if (data.message) return reasons(data.message);
    return Object.values(data).map(reasons).filter(Boolean).join('\n');
  }
  return '';
}

// Route JSON stays at this boundary rather than duplicating Part 3's Pydantic
// models. Lens types are imported directly from the shared app contract.
export type JsonObject = Record<string, any>;
export async function api(path: string, init: RequestInit = {}): Promise<any> {
  if (!path.startsWith('/v1/') || path.includes('://')) throw new Error('API requests must use the same origin');
  const token = sessionStorage.getItem(TOKEN_KEY);
  if (!token) throw new ApiError(401, 'Enter your workspace code to continue.');
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(path, { ...init, headers, signal: init.signal ?? AbortSignal.timeout(15000) });
  if (response.status === 401) {
    sessionStorage.removeItem(TOKEN_KEY);
    window.dispatchEvent(new Event('portal:unauthorized'));
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new ApiError(response.status, reasons(detail) || `Request failed (${response.status}). Try again.`);
  }
  if (response.status === 204) return null;
  return response.headers.get('content-type')?.includes('image/') ? response.blob() : response.json();
}
export function json(method: string, data?: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: data === undefined ? undefined : JSON.stringify(data) };
}

export function poll(action: () => Promise<void>, milliseconds: number): () => void {
  let busy = false, stopped = false;
  const tick = async () => {
    if (busy || stopped) return;
    busy = true;
    try { await action(); } finally { busy = false; }
  };
  const timer = setInterval(() => { void tick(); }, milliseconds);
  void tick();
  return () => { stopped = true; clearInterval(timer); };
}
