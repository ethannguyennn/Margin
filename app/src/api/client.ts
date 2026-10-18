// The only place the app talks to the relay. Timeout, abort, one retry, and every
// failure mapped onto the contract error shape so Part 1 only switches on `outcome`.
import type { AskRequest, AskResponse, Assignment, Command, DiagramImage, Outcome, Pairing, ProgressEvent } from '../types.ts';
import { ASK_TIMEOUT_MS, MOCK, RELAY_ORIGIN, SESSION_ID, getDevice, setDevice } from '../settings.ts';
import {
  mockAsk,
  mockGetDiagram,
  mockHealth,
  mockLogDeviation,
  mockNextAssignment,
  mockPair,
  mockPairingStatus,
  mockPostProgress,
} from '../mock/index.ts';
import { captureError, logAsk, span, traceHeaders, traceSpan } from '../obs/sentry.ts';

/** Client-side codes on top of the relay's stt_failed | db_down | llm_timeout | bad_request. */
export type ErrorCode =
  | 'stt_failed'
  | 'db_down'
  | 'llm_timeout'
  | 'bad_request'
  | 'network'
  | 'timeout'
  | 'unauthorized' // 401 on a lens route: the token was dropped, call pair() again
  | 'not_found'
  | 'server_error';

const OUTCOMES: Outcome[] = ['answered', 'not_found', 'logged', 'clarify', 'command', 'error'];
const COMMANDS: Command[] = ['next', 'back', 'repeat', 'details', 'diagram', 'pause', 'resume', 'exit'];

function authHeader(): Record<string, string> {
  const d = getDevice();
  return d ? { authorization: `Bearer ${d.device_token}` } : {};
}

const EMPTY_LATENCY = { stt: 0, embed: 0, retrieve: 0, generate: 0, verify: 0, total: 0 };

function quotaFailure(code: unknown, message: unknown): boolean {
  return code === 'rate_limited' || code === 'quota_exceeded' || message === 'Busy, try again'
    || (typeof message === 'string' && /\b429\b|\bquota\b|resource_exhausted/i.test(message));
}

function errorResponse(code: ErrorCode, message: string, trace_id = ''): AskResponse {
  if (quotaFailure(code, message)) message = 'Busy, try again';
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
    latency_ms: r.latency_ms ?? EMPTY_LATENCY,
    ...(typeof r.needs_clarification === 'boolean' ? { needs_clarification: r.needs_clarification } : {}),
    ...(r.error ? { error: r.error } : {}),
  };
  if (res.outcome === 'error' && !res.error) {
    return errorResponse('network', 'error outcome with no error body', res.trace_id);
  }
  if (res.outcome === 'error' && res.error && quotaFailure(res.error.code, res.error.message)) {
    res.error = { ...res.error, message: 'Busy, try again' };
  }
  if (res.outcome === 'command') {
    // The lens acts on `command` and never renders a command as text.
    if (!r.command || !COMMANDS.includes(r.command)) {
      return errorResponse('bad_request', `command outcome with unknown command ${String(r.command)}`, res.trace_id);
    }
    return { ...res, command: r.command, glance: '', body: '', citations: [], verified: false };
  }
  if (res.outcome === 'answered' && (!res.verified || res.citations.length === 0)) {
    console.warn('[client] unverified answer downgraded to not_found', res.trace_id);
    return notFound(res);
  }
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
          ...authHeader(),
          ...traceHeaders(),
        },
        body: JSON.stringify({ ...req, session_id: req.session_id || SESSION_ID }),
        signal: ctrl.signal,
      }),
    );
    if (res.ok) return { res, body: await res.json().catch(() => null) };
    const body = await res.json().catch(() => null);
    if (res.status === 401) dropToken();
    return {
      res,
      body,
      code: res.status >= 500 ? 'db_down' : res.status === 401 ? 'unauthorized' : 'bad_request',
      message: `relay returned HTTP ${res.status}`,
      retryable: res.status >= 500 && !quotaFailure(
        (body as Partial<AskResponse> | null)?.error?.code,
        (body as Partial<AskResponse> | null)?.error?.message), // don't replay audio into exhausted quota
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

// --- v2: device, assignment, progress and diagram routes ---------------------
// Same rules as ask: exact origin, timeout, one retry on network/5xx, never on a 4xx.
// Failures reject with a RelayError carrying a typed ErrorCode; nothing else is thrown.

export class RelayError extends Error {
  constructor(
    readonly code: ErrorCode,
    message: string,
    readonly status = 0,
  ) {
    super(message);
    this.name = 'RelayError';
  }
}

/** 401 on a lens route: the token is dead. Part 1 sees code 'unauthorized' and calls pair(). */
function dropToken(): void {
  if (getDevice()) console.warn('[client] relay rejected the device token; dropping it, re-pair needed');
  setDevice(null);
}

async function call(method: 'GET' | 'POST', path: string, body?: unknown, auth = true): Promise<{ status: number; body: unknown }> {
  if (!RELAY_ORIGIN) throw new RelayError('bad_request', 'VITE_RELAY_ORIGIN is not set');
  if (auth && !getDevice()) throw new RelayError('unauthorized', 'not paired');
  const once = async (): Promise<{ status: number; body: unknown } | RelayError> => {
    try {
      const res = await fetch(`${RELAY_ORIGIN}${path}`, {
        method,
        headers: {
          'x-session-id': SESSION_ID,
          ...(body === undefined ? {} : { 'content-type': 'application/json' }),
          ...(auth ? authHeader() : {}),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        signal: AbortSignal.timeout ? AbortSignal.timeout(ASK_TIMEOUT_MS) : undefined,
      });
      if (res.status === 204) return { status: 204, body: null };
      const json = await res.json().catch(() => null);
      if (res.ok) return { status: res.status, body: json };
      if (res.status === 401) {
        dropToken();
        return new RelayError('unauthorized', `${path}: HTTP 401`, 401);
      }
      if (res.status === 404) return new RelayError('not_found', `${path}: HTTP 404`, 404);
      return new RelayError(res.status >= 500 ? 'server_error' : 'bad_request', `${path}: HTTP ${res.status}`, res.status);
    } catch (e) {
      const name = (e as Error)?.name;
      return new RelayError(name === 'TimeoutError' ? 'timeout' : 'network', `${path}: ${(e as Error)?.message ?? 'network error'}`);
    }
  };
  let r = await once();
  // Exactly one retry, and only for network errors and 5xx.
  if (r instanceof RelayError && (r.code === 'network' || r.code === 'server_error')) r = await once();
  if (r instanceof RelayError) throw r;
  return r;
}

const isStr = (v: unknown): v is string => typeof v === 'string' && v.length > 0;

function toPairing(raw: unknown, keepToken?: string): Pairing {
  const p = (raw ?? {}) as Partial<Pairing>;
  const device_token = isStr(p.device_token) ? p.device_token : keepToken;
  if (!isStr(p.device_id) || !isStr(device_token) || typeof p.pair_code !== 'string') {
    throw new RelayError('bad_request', 'malformed pairing from relay');
  }
  return {
    device_id: p.device_id,
    device_token,
    pair_code: p.pair_code,
    claimed: p.claimed === true,
    worker_name: typeof p.worker_name === 'string' ? p.worker_name : null,
  };
}

/** First boot: mint a device + pair code. Stores the credential via settings.ts. */
export async function pair(): Promise<Pairing> {
  const p = toPairing(MOCK ? await mockPair() : (await call('POST', '/v1/devices/pair', { session_id: SESSION_ID }, false)).body);
  setDevice({ device_id: p.device_id, device_token: p.device_token });
  return p;
}

/** Polled by Part 1 while the lens shows the pair code, until claimed. */
export async function pairingStatus(): Promise<Pairing> {
  if (MOCK) return toPairing(await mockPairingStatus());
  return toPairing((await call('GET', '/v1/devices/me')).body, getDevice()?.device_token);
}

/** null on 204 (nothing assigned). Part 1 polls; this does not. */
export async function nextAssignment(): Promise<Assignment | null> {
  const raw = MOCK ? await mockNextAssignment() : (await call('GET', '/v1/assignments/next')).body;
  if (raw === null) return null;
  const a = raw as Partial<Assignment>;
  const w = a.walkthrough;
  if (!isStr(a.assignment_id) || !w || !Array.isArray(w.steps) || w.steps.length === 0) {
    throw new RelayError('bad_request', 'malformed assignment from relay');
  }
  return {
    assignment_id: a.assignment_id,
    assigned_at: a.assigned_at ?? '',
    walkthrough: { ...w, assignment_id: w.assignment_id ?? a.assignment_id },
  };
}

// Progress: fire-and-forget for Part 1, durable here. Text only, capped, mirrored to
// localStorage so a reload or an airplane-mode stretch loses nothing. The relay is
// idempotent on (assignment_id, step_id, kind, ts), so resending a batch is safe.
const QUEUE_KEY = 'specs.progressQueue';
const QUEUE_CAP = 200;
const FLUSH_EVERY = 10;
const FLUSH_MS = 5000;
const MAX_BACKOFF_MS = 60000;

function loadQueue(): ProgressEvent[] {
  try {
    const q = JSON.parse(localStorage.getItem(QUEUE_KEY) ?? '[]') as ProgressEvent[];
    return Array.isArray(q) ? q.filter((e) => isStr(e?.assignment_id) && isStr(e?.kind) && typeof e.ts === 'number') : [];
  } catch {
    return [];
  }
}
let queue: ProgressEvent[] = loadQueue();
let flushTimer: ReturnType<typeof setTimeout> | null = null;
let flushing: Promise<void> | null = null;
let backoffMs = 0;
let lifecycleHooked = false;

function persistQueue(): void {
  try {
    localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
  } catch {
    /* in-memory only this session */
  }
}

function scheduleFlush(ms: number): void {
  if (flushTimer) return;
  flushTimer = setTimeout(() => {
    flushTimer = null;
    void flushProgress();
  }, ms);
}

/** Flush on the host FOREGROUND_EXIT_EVENT, on hide, and as soon as the network is back. */
async function hookLifecycle(): Promise<void> {
  if (lifecycleHooked || typeof window === 'undefined') return;
  lifecycleHooked = true;
  window.addEventListener('online', () => void flushProgress());
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') void flushProgress();
  });
  try {
    const { getBridge } = await import('../audio/capture.ts');
    (await getBridge()).onEvenHubEvent((e) => {
      if (e.sysEvent?.eventType === 5) void flushProgress(); // FOREGROUND_EXIT_EVENT
    });
  } catch {
    /* no bridge (browser preview): online and visibility still flush */
  }
}

export function reportProgress(ev: ProgressEvent): void {
  queue.push({ assignment_id: ev.assignment_id, step_id: ev.step_id ?? null, kind: ev.kind, ts: ev.ts });
  if (queue.length > QUEUE_CAP) queue.splice(0, queue.length - QUEUE_CAP); // drop oldest
  persistQueue();
  void hookLifecycle();
  if (queue.length >= FLUSH_EVERY) void flushProgress();
  else scheduleFlush(backoffMs || FLUSH_MS);
}

/** Send everything queued as one batch. Exported for tests and for the exit path. */
export function flushProgress(): Promise<void> {
  if (flushing) return flushing;
  if (queue.length === 0) return Promise.resolve();
  if (flushTimer) clearTimeout(flushTimer);
  flushTimer = null;
  const batch = queue.slice();
  flushing = (async () => {
    try {
      if (MOCK) await mockPostProgress(batch);
      else await call('POST', '/v1/progress', { events: batch });
      backoffMs = 0;
      drop(batch);
    } catch (e) {
      const code = e instanceof RelayError ? e.code : 'network';
      if (code === 'bad_request' || code === 'not_found') {
        // Never retry a 4xx: the relay will not accept these, keeping them would wedge the queue.
        console.warn('[client] progress batch rejected, dropping', (e as Error).message);
        drop(batch);
      } else {
        // Offline, 5xx or unpaired: keep everything and back off (5 s, 10 s ... 60 s).
        backoffMs = Math.min(MAX_BACKOFF_MS, backoffMs ? backoffMs * 2 : FLUSH_MS);
      }
    } finally {
      flushing = null;
      if (queue.length) scheduleFlush(backoffMs || FLUSH_MS);
    }
  })();
  return flushing;
}

/** Remove exactly the events that were sent; anything queued meanwhile stays. */
function drop(sent: ProgressEvent[]): void {
  const s = new Set(sent);
  queue = queue.filter((e) => !s.has(e));
  persistQueue();
}

/** For tests and the dev page. */
export function pendingProgress(): readonly ProgressEvent[] {
  return queue;
}

// Diagrams: an LRU of 8, concurrent fetches of one id share a request, and each tile
// arrives decoded into the bytes updateImageRawData takes (number[], per the SDK docs).
export type LensTile = DiagramImage['tiles'][number] & { bytes: number[] };
export interface LensDiagram extends DiagramImage {
  tiles: LensTile[];
}

const DIAGRAM_CACHE = 8;
const diagrams = new Map<string, LensDiagram>();
const fetching = new Map<string, Promise<LensDiagram>>();
const PNG_MAGIC = [137, 80, 78, 71, 13, 10, 26, 10];

function fromBase64(s: string): number[] {
  const g = globalThis as { atob?: (s: string) => string; Buffer?: { from: (s: string, e: string) => Uint8Array } };
  if (g.atob) return Array.from(g.atob(s), (c) => c.charCodeAt(0));
  return Array.from(g.Buffer!.from(s, 'base64'));
}

/** Tiles are 8-bit grey PNG (proven format) or packed 4-bit, high nibble = left pixel. */
function toLensDiagram(raw: unknown, id: string): LensDiagram {
  const d = (raw ?? {}) as Partial<DiagramImage>;
  if (!Array.isArray(d.tiles) || d.tiles.length < 1 || d.tiles.length > 2) {
    throw new RelayError('bad_request', `diagram ${id}: expected 1-2 tiles`);
  }
  const tiles = d.tiles.map((t): LensTile => {
    const ok = (t.slot === 0 || t.slot === 1) && t.width >= 20 && t.width <= 288 && t.height >= 20 && t.height <= 144;
    if (!ok || !isStr(t.image)) throw new RelayError('bad_request', `diagram ${id}: bad tile`);
    let bytes: number[];
    try {
      bytes = fromBase64(t.image);
    } catch {
      throw new RelayError('bad_request', `diagram ${id}: tile is not base64`);
    }
    const png = PNG_MAGIC.every((b, i) => bytes[i] === b);
    if (!png && bytes.length !== (t.width * t.height) / 2) {
      throw new RelayError('bad_request', `diagram ${id}: tile is neither PNG nor packed 4-bit`);
    }
    return { slot: t.slot, width: t.width, height: t.height, image: t.image, bytes };
  });
  return { diagram_id: d.diagram_id ?? id, tiles };
}

async function fetchDiagram(id: string): Promise<LensDiagram> {
  const t0 = Date.now();
  try {
    const raw = MOCK ? await mockGetDiagram(id) : (await call('GET', `/v1/diagrams/${encodeURIComponent(id)}`)).body;
    if (!raw) throw new RelayError('not_found', `diagram ${id} not found`, 404);
    const d = toLensDiagram(raw, id);
    span('diagram_fetch', t0, { diagram_id: id, outcome: 'ok' });
    return d;
  } catch (e) {
    span('diagram_fetch', t0, { diagram_id: id, outcome: e instanceof RelayError ? e.code : 'error' });
    throw e;
  }
}

/** Cached and de-duplicated. Prefetch = call and ignore the promise (it never goes unhandled). */
export function getDiagram(diagram_id: string): Promise<LensDiagram> {
  const hit = diagrams.get(diagram_id);
  if (hit) {
    diagrams.delete(diagram_id); // refresh LRU position
    diagrams.set(diagram_id, hit);
    return Promise.resolve(hit);
  }
  const pending = fetching.get(diagram_id);
  if (pending) return pending;
  const p = fetchDiagram(diagram_id)
    .then((d) => {
      diagrams.set(diagram_id, d);
      while (diagrams.size > DIAGRAM_CACHE) diagrams.delete(diagrams.keys().next().value!);
      return d;
    })
    .finally(() => fetching.delete(diagram_id));
  p.catch(() => {}); // a prefetch nobody awaits must not surface as an unhandled rejection
  fetching.set(diagram_id, p);
  return p;
}
