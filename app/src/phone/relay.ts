// The phone screen's own relay calls: health, procedures, steps, deviations, and asks
// when no glasses are connected (browser preview). With the lens connected, asks go
// through the lens controller instead (lens-link.ts) so the glasses show them too.
// Same origin and timeout as the lens client (settings.ts), so one whitelist entry.
import type { AskResponse, DeviationResult, Health, Procedure, Step } from './contract';
import type { StepContext } from './session';
import { ASK_TIMEOUT_MS, RELAY_ORIGIN } from '../settings';

const ORIGIN = RELAY_ORIGIN;
const TIMEOUT_MS = ASK_TIMEOUT_MS;

export const relayOrigin = ORIGIN;

export class RelayError extends Error {
  constructor(
    public code: string,
    message: string,
    public traceId = '',
  ) {
    super(message);
    this.name = 'RelayError';
  }
}

export function asRelayError(e: unknown): RelayError {
  if (e instanceof RelayError) return e;
  return new RelayError('network', (e as Error)?.message ?? 'relay unreachable');
}

async function request<T>(
  path: string,
  opts: { method: 'GET' | 'POST'; sessionId: string; body?: unknown },
): Promise<T> {
  if (!ORIGIN) throw new RelayError('bad_request', 'VITE_RELAY_ORIGIN is not set');

  let res: Response;
  try {
    res = await fetch(`${ORIGIN}${path}`, {
      method: opts.method,
      headers: { 'content-type': 'application/json', 'x-session-id': opts.sessionId },
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (e) {
    const timedOut = (e as Error)?.name === 'TimeoutError';
    throw new RelayError('network', timedOut ? `no answer in ${TIMEOUT_MS} ms` : 'relay unreachable');
  }

  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    // The relay's own error body wins over our guess, when it sent a usable one.
    const err = body as { trace_id?: string; error?: { code?: string; message?: string } } | null;
    throw new RelayError(
      err?.error?.code ?? 'network',
      err?.error?.message ?? `relay returned HTTP ${res.status}`,
      err?.trace_id ?? '',
    );
  }
  return body as T;
}

export function health(sessionId: string): Promise<Health> {
  return request<Health>('/v1/health', { method: 'GET', sessionId });
}

export function listProcedures(sessionId: string): Promise<Procedure[]> {
  return request<Procedure[]>('/v1/procedures', { method: 'GET', sessionId });
}

export function listSteps(sessionId: string, docId: string, revision: string | null): Promise<Step[]> {
  const q = revision ? `?revision=${encodeURIComponent(revision)}` : '';
  return request<Step[]>(`/v1/procedures/${encodeURIComponent(docId)}/steps${q}`, { method: 'GET', sessionId });
}

/** Exactly the AskRequest shape: extra keys are rejected (schemas.py forbids them). */
export function ask(sessionId: string, text: string, context: StepContext): Promise<AskResponse> {
  return request<AskResponse>('/v1/ask', {
    method: 'POST',
    sessionId,
    body: { session_id: sessionId, text, context },
  });
}

export function logDeviation(
  sessionId: string,
  text: string,
  context: StepContext,
): Promise<DeviationResult> {
  return request<DeviationResult>('/v1/deviation', {
    method: 'POST',
    sessionId,
    body: { session_id: sessionId, text, context },
  });
}
