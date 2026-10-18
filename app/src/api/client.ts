// The only place the app talks to the relay. Timeout, abort, one retry, and every
// failure mapped onto the contract error shape so Part 1 only switches on `outcome`.
import type { AskRequest, AskResponse, Outcome } from '../types.ts';
import { ASK_TIMEOUT_MS, MOCK, RELAY_ORIGIN, SESSION_ID } from '../settings.ts';
import { mockAsk, mockHealth, mockLogDeviation } from '../mock/index.ts';
import { captureError, logAsk, traceHeaders, traceSpan } from '../obs/sentry.ts';
import { parseDisplay } from '../ui/generated-display';
import { answerGraphic } from '../ui/sop-graphics';

/** Client-side codes on top of the relay's stt_failed | db_down | llm_timeout | bad_request. */
export type ErrorCode = 'stt_failed' | 'db_down' | 'llm_timeout' | 'bad_request' | 'network' | 'timeout';

const OUTCOMES: Outcome[] = ['answered', 'not_found', 'logged', 'clarify', 'error'];

const EMPTY_LATENCY = { stt: 0, embed: 0, retrieve: 0, generate: 0, verify: 0, total: 0 };

function errorResponse(code: ErrorCode, message: string, trace_id = ''): AskResponse {
  captureError(code, message);
  return {
    trace_id,
    transcript: '',
    intent: 'unknown',
    outcome: 'error',
    glance: '',
    body: '',
    source: '',
    citations: [],
    verified: false,
    walkthrough: null,
    display: null,
    graphic_id: null,
    latency_ms: EMPTY_LATENCY,
    error: { code, message },
  };
}

function notFound(raw: Partial<AskResponse>): AskResponse {
  return {
    ...(raw as AskResponse),
    outcome: 'not_found',
    glance: 'Not in approved SOPs',
    body: 'No matching procedure. Try rephrasing or ask your supervisor.',
    citations: [],
    verified: false,
    walkthrough: null,
    display: null,
    graphic_id: null,
  };
}

/** Minimal shape check. The relay should never send an unverified answer; this is the belt. */
function validate(raw: unknown): AskResponse {
  if (!raw || typeof raw !== 'object') return errorResponse('network', 'empty response from relay');
  const r = raw as Partial<AskResponse>;
  if (!r.outcome || !OUTCOMES.includes(r.outcome)) {
    return errorResponse('network', `unknown outcome ${String(r.outcome)}`, r.trace_id ?? '');
  }
  const res: AskResponse = {
    trace_id: r.trace_id ?? '',
    transcript: r.transcript ?? '',
    intent: r.intent ?? 'unknown',
    outcome: r.outcome,
    glance: r.glance ?? '',
    body: r.body ?? '',
    source: r.source ?? '',
    citations: r.citations ?? [],
    verified: r.verified === true,
    walkthrough: r.walkthrough ?? null,
    display: r.outcome === 'answered' && r.verified === true ? parseDisplay(r.display) : null,
    ...(r.graphic_id !== undefined ? { graphic_id: r.graphic_id } : {}),
    latency_ms: r.latency_ms ?? EMPTY_LATENCY,
    ...(r.error ? { error: r.error } : {}),
  };
  if (res.outcome === 'error' && !res.error) {
    return errorResponse('network', 'error outcome with no error body', res.trace_id);
  }
  if (res.outcome === 'answered' && (!res.verified || res.citations.length === 0)) {
    console.warn('[client] unverified answer downgraded to not_found', res.trace_id);
    return notFound(res);
  }
  res.graphic_id = answerGraphic(res)?.id ?? null;
  return res;
}

/** A new press aborts the ask that is already in flight. */
let inflight: AbortController | null = null;

type Attempt = { res?: Response; body?: unknown; code?: ErrorCode; message?: string; retryable?: boolean };

async function attempt(req: AskRequest, external?: AbortSignal): Promise<Attempt> {
  const ctrl = new AbortController();
  inflight = ctrl;
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    ctrl.abort();
  }, ASK_TIMEOUT_MS);
  const onExternalAbort = () => ctrl.abort();
  external?.addEventListener('abort', onExternalAbort);
  try {
    const res = await traceSpan('upload', () =>
      fetch(`${RELAY_ORIGIN}/v1/ask`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          'x-session-id': req.session_id || SESSION_ID,
          ...traceHeaders(),
        },
        body: JSON.stringify({ ...req, session_id: req.session_id || SESSION_ID }),
        signal: ctrl.signal,
      }),
    );
    if (res.ok) return { res, body: await res.json().catch(() => null) };
    const body = await res.json().catch(() => null);
    return {
      res,
      body,
      code: res.status >= 500 ? 'db_down' : 'bad_request',
      message: `relay returned HTTP ${res.status}`,
      retryable: res.status >= 500, // never retry a 4xx
    };
  } catch (e) {
    if (timedOut) return { code: 'timeout', message: `no answer in ${ASK_TIMEOUT_MS} ms`, retryable: false };
    if (ctrl.signal.aborted) return { code: 'network', message: 'request cancelled', retryable: false };
    return { code: 'network', message: (e as Error)?.message ?? 'network error', retryable: true };
  } finally {
    clearTimeout(timer);
    external?.removeEventListener('abort', onExternalAbort);
    if (inflight === ctrl) inflight = null;
  }
}

async function askInner(req: AskRequest, opts?: { signal?: AbortSignal }): Promise<AskResponse> {
  if (MOCK) return mockAsk(req);
  if (!RELAY_ORIGIN) return errorResponse('bad_request', 'VITE_RELAY_ORIGIN is not set');

  inflight?.abort(); // a new press wins

  let a = await attempt(req, opts?.signal);
  if (a.retryable) a = await attempt(req, opts?.signal); // exactly one retry
  if (a.code) {
    // The relay's own error body wins over our guess, when it sent a usable one.
    const served = a.body as Partial<AskResponse> | null;
    if (served?.outcome === 'error' && served.error?.code) {
      return validate(served);
    }
    return errorResponse(a.code, a.message ?? a.code, served?.trace_id ?? '');
  }
  return validate(a.body);
}

export async function ask(req: AskRequest, opts?: { signal?: AbortSignal }): Promise<AskResponse> {
  const t0 = Date.now();
  const res = await askInner(req, opts);
  logAsk(res.outcome, Date.now() - t0, res.trace_id);
  return res;
}

export async function health(): Promise<{ ok: boolean; mock: boolean; db: string; version: string }> {
  if (MOCK) return mockHealth();
  try {
    const res = await fetch(`${RELAY_ORIGIN}/v1/health`, {
      headers: { 'x-session-id': SESSION_ID },
      signal: AbortSignal.timeout ? AbortSignal.timeout(3000) : undefined,
    });
    if (!res.ok) return { ok: false, mock: false, db: 'unknown', version: 'unknown' };
    const b = (await res.json()) as Partial<{ ok: boolean; mock: boolean; db: string; version: string }>;
    return { ok: b.ok === true, mock: b.mock === true, db: b.db ?? 'unknown', version: b.version ?? 'unknown' };
  } catch {
    return { ok: false, mock: false, db: 'unreachable', version: 'unknown' };
  }
}

export async function logDeviation(
  text: string,
  ctx?: { doc_id?: string; step_id?: string },
): Promise<{ deviation_id: string; notified: boolean }> {
  if (MOCK) return mockLogDeviation();
  try {
    const res = await fetch(`${RELAY_ORIGIN}/v1/deviation`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-session-id': SESSION_ID },
      body: JSON.stringify({
        session_id: SESSION_ID,
        text,
        context: { doc_id: ctx?.doc_id ?? null, step_id: ctx?.step_id ?? null },
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const b = (await res.json()) as Partial<{ deviation_id: string; notified: boolean }>;
    return { deviation_id: b.deviation_id ?? '', notified: b.notified === true };
  } catch (e) {
    captureError('network', `deviation log failed: ${(e as Error)?.message}`);
    return { deviation_id: '', notified: false };
  }
}
