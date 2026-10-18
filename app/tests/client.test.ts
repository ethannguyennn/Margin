// Run: npm test
import { test } from 'vitest';
import assert from 'node:assert/strict';

process.env.VITE_RELAY_ORIGIN = 'http://relay.test';
process.env.VITE_MOCK = '0';

// The WebView's localStorage, before the client loads its persisted progress queue.
const store: Record<string, string> = {};
(globalThis as any).localStorage = {
  getItem: (k: string) => store[k] ?? null,
  setItem: (k: string, v: string) => void (store[k] = String(v)),
  removeItem: (k: string) => void delete store[k],
};

const { ask } = await import('../src/api/client.ts');
const { mockResponseFor, fixtures } = await import('../src/mock/index.ts');

const REQ = { session_id: 's', text: 'how tight is the m5' };

const ANSWERED = {
  trace_id: 't1',
  transcript: 'how tight is the m5',
  intent: 'question',
  outcome: 'answered',
  glance: 'Step 4.2: torque M5 to 4 N-m',
  body: 'Torque to 4 N-m.',
  source: 'SOP-114 Sec 4.2 rev C',
  citations: [{ chunk_id: 'SOP-114:C:4.2', doc_id: 'SOP-114', revision: 'C', section: '4.2', quote: 'q' }],
  verified: true,
  walkthrough: null,
  latency_ms: { stt: 1, embed: 1, retrieve: 1, generate: 1, verify: 1, total: 5 },
};

/** Replaces global fetch, counts calls, and returns the queued responses in order. */
function stubFetch(...replies: Array<{ status?: number; body?: unknown } | Error>) {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  let i = 0;
  (globalThis as any).fetch = async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    const r = replies[Math.min(i++, replies.length - 1)];
    if (r instanceof Error) throw r;
    const status = r.status ?? 200;
    return { ok: status >= 200 && status < 300, status, json: async () => r.body };
  };
  return calls;
}

test('200 answered passes through and sends x-session-id', async () => {
  const calls = stubFetch({ body: ANSWERED });
  const res = await ask(REQ);
  assert.equal(res.outcome, 'answered');
  assert.equal(res.glance, ANSWERED.glance);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'http://relay.test/v1/ask');
  assert.ok((calls[0].init.headers as Record<string, string>)['x-session-id']);
});

test('answered without verified is downgraded to not_found', async () => {
  stubFetch({ body: { ...ANSWERED, verified: false } });
  const res = await ask(REQ);
  assert.equal(res.outcome, 'not_found');
  assert.equal(res.glance, 'Not in approved SOPs');
  assert.deepEqual(res.citations, []);
});

test('answered with no citations is downgraded to not_found', async () => {
  stubFetch({ body: { ...ANSWERED, citations: [] } });
  assert.equal((await ask(REQ)).outcome, 'not_found');
});

test('unknown outcome becomes an error', async () => {
  stubFetch({ body: { ...ANSWERED, outcome: 'maybe' } });
  const res = await ask(REQ);
  assert.equal(res.outcome, 'error');
  assert.equal(res.error?.code, 'network');
});

test('5xx is retried exactly once', async () => {
  const calls = stubFetch({ status: 500, body: null });
  const res = await ask(REQ);
  assert.equal(calls.length, 2);
  assert.equal(res.outcome, 'error');
  assert.equal(res.error?.code, 'db_down');
});

test('4xx is never retried', async () => {
  const calls = stubFetch({ status: 400, body: null });
  const res = await ask(REQ);
  assert.equal(calls.length, 1);
  assert.equal(res.error?.code, 'bad_request');
});

test('HTTP 429 shows busy and never repeats the upload', async () => {
  const calls = stubFetch({ status: 429 });
  const res = await ask(REQ);
  assert.equal(res.error?.message, 'Busy, try again');
  assert.equal(res.verified, false);
  assert.equal(calls.length, 1);
});

test('provider quota wrapped in a relay 504 shows busy without retrying', async () => {
  const calls = stubFetch({ status: 504, body: {
    outcome: 'error', error: { code: 'llm_timeout', message: 'Gemini HTTP 429 RESOURCE_EXHAUSTED' },
  } });
  assert.equal((await ask(REQ)).error?.message, 'Busy, try again');
  assert.equal(calls.length, 1);
});

test('a successful HTTP envelope carrying a quota error also shows busy', async () => {
  stubFetch({ body: { ...ANSWERED, outcome: 'error', verified: false,
    error: { code: 'rate_limited', message: 'provider limit' } } });
  assert.equal((await ask(REQ)).error?.message, 'Busy, try again');
});

test('safe relay quota copy suppresses the normal 5xx retry', async () => {
  const calls = stubFetch({ status: 504, body: {
    outcome: 'error', error: { code: 'llm_timeout', message: 'Busy, try again' },
  } });
  assert.equal((await ask(REQ)).error?.message, 'Busy, try again');
  assert.equal(calls.length, 1);
});

test("the relay's own error code wins over ours", async () => {
  stubFetch({ status: 503, body: { trace_id: 't9', outcome: 'error', error: { code: 'llm_timeout', message: 'slow' } } });
  const res = await ask(REQ);
  assert.equal(res.error?.code, 'llm_timeout');
  assert.equal(res.trace_id, 't9');
});

test('a network error retries once then maps to code network', async () => {
  const calls = stubFetch(new Error('connection refused'));
  const res = await ask(REQ);
  assert.equal(calls.length, 2);
  assert.equal(res.error?.code, 'network');
});

test('a second ask aborts the first', async () => {
  const signals: AbortSignal[] = [];
  (globalThis as any).fetch = (_url: string, init: RequestInit) =>
    new Promise((_resolve, reject) => {
      signals.push(init.signal as AbortSignal);
      (init.signal as AbortSignal).addEventListener('abort', () => reject(new Error('aborted')));
    });
  const first = ask(REQ);
  stubFetch({ body: ANSWERED });
  const second = await ask(REQ);
  assert.equal(signals[0].aborted, true);
  assert.equal((await first).error?.code, 'network');
  assert.equal(second.outcome, 'answered');
});

test('mock fixtures cover the whole trigger table', () => {
  assert.equal(mockResponseFor('how tight is the m5').outcome, 'answered');
  assert.equal(mockResponseFor('TORQUE the bracket').source, 'SOP-114 Sec 4.2 rev C');
  assert.equal(mockResponseFor('walk me through it').walkthrough?.steps.length, 7);
  assert.ok(mockResponseFor('how do i clean it').body.length > 600); // paginates to 2 pages
  assert.equal(mockResponseFor('log deviation, screw was stripped').outcome, 'logged');
  assert.equal(mockResponseFor('boom').error?.code, 'llm_timeout');
  assert.equal(mockResponseFor('where is the good coffee').outcome, 'not_found');
  assert.equal(fixtures.NOT_FOUND.glance, 'Not in approved SOPs');
});

test('session ids are UUIDs even without crypto.randomUUID (insecure WebView)', async () => {
  const { uuid } = await import('../src/settings.ts');
  const re = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  assert.match(uuid(), re);
  const orig = Object.getOwnPropertyDescriptor(globalThis.crypto, 'randomUUID');
  Object.defineProperty(globalThis.crypto, 'randomUUID', { value: undefined, configurable: true });
  try {
    for (let i = 0; i < 50; i++) assert.match(uuid(), re); // the relay rejects anything else
  } finally {
    if (orig) Object.defineProperty(globalThis.crypto, 'randomUUID', orig);
    else delete (globalThis.crypto as any).randomUUID;
  }
});

test('x-session-id follows the request session_id', async () => {
  const calls = stubFetch({ body: ANSWERED });
  await ask({ session_id: '7f1c0c4e-2b2a-4c1e-9d0e-0a1b2c3d4e5f', text: 'torque' });
  assert.equal((calls[0].init.headers as Record<string, string>)['x-session-id'], '7f1c0c4e-2b2a-4c1e-9d0e-0a1b2c3d4e5f');
});

// app/src/main.ts loads these through import.meta.glob and casts them, so tsc cannot
// catch a mismatch - this test does. Keep in sync with CaptureModule/ClientModule/ObsModule.
test("Part 2 modules export exactly what Part 1's main.ts calls", async () => {
  const audio = await import('../src/audio/capture.ts');
  const client = await import('../src/api/client.ts');
  const obs = await import('../src/obs/sentry.ts');
  for (const fn of [audio.startCapture, audio.stopCapture, audio.isCapturing, client.ask, obs.initObs, obs.startAsk]) {
    assert.equal(typeof fn, 'function');
  }
  const span = obs.startAsk(); // no DSN -> no-op handle, never throws
  span.finishSpan('render');
  span.end('answered');
});

// --- v2 -----------------------------------------------------------------------
const client = await import('../src/api/client.ts');
const settings = await import('../src/settings.ts');
const mock = await import('../src/mock/index.ts');
const { mockDiagramImage } = await import('../src/mock/tiles.ts');
const { vi } = await import('vitest');
const headers = (c: { init: RequestInit }) => (c.init.headers ?? {}) as Record<string, string>;
const paired = () => settings.setDevice({ device_id: 'd1', device_token: 'tok-1' });
const rejects = async (p: Promise<unknown>, code: string) => {
  await assert.rejects(p, (e: any) => e instanceof client.RelayError && e.code === code);
};

test('command outcome with a known command passes, never carries text', async () => {
  stubFetch({ body: { ...ANSWERED, intent: 'command', outcome: 'command', command: 'next', glance: 'x', verified: true } });
  const res = await ask(REQ);
  assert.equal(res.outcome, 'command');
  assert.equal(res.command, 'next');
  assert.equal(res.glance, '');
  assert.deepEqual(res.citations, []);
  assert.equal(res.verified, false);
});

test('command outcome without a known command value is downgraded to error', async () => {
  for (const command of ['jump', undefined, null]) {
    stubFetch({ body: { ...ANSWERED, outcome: 'command', command } });
    const res = await ask(REQ);
    assert.equal(res.outcome, 'error', String(command));
    assert.equal(res.error?.code, 'bad_request');
  }
});

test('needs_clarification passes through; assignment context is sent as given', async () => {
  const calls = stubFetch({ body: { ...ANSWERED, needs_clarification: true } });
  const res = await ask({ ...REQ, context: { doc_id: 'SOP-114', step_id: 's1', assignment_id: 'a1' } });
  assert.equal(res.needs_clarification, true);
  assert.equal(JSON.parse(calls[0].init.body as string).context.assignment_id, 'a1');
});

test('ask sends the device token when paired; a 401 drops it', async () => {
  paired();
  const calls = stubFetch({ status: 401, body: null });
  const res = await ask(REQ);
  assert.equal(headers(calls[0]).authorization, 'Bearer tok-1');
  assert.equal(calls.length, 1, '401 is not retried');
  assert.equal(res.error?.code, 'unauthorized');
  assert.equal(settings.getDevice(), null);
});

test('pair: no auth header, stores the credential, returns the code', async () => {
  settings.setDevice(null);
  const calls = stubFetch({ body: { device_id: 'd9', device_token: 'tok-9', pair_code: '4F7K', claimed: false, worker_name: null } });
  const p = await client.pair();
  assert.equal(calls[0].url, 'http://relay.test/v1/devices/pair');
  assert.equal(calls[0].init.method, 'POST');
  assert.equal(headers(calls[0]).authorization, undefined);
  assert.ok(JSON.parse(calls[0].init.body as string).session_id);
  assert.equal(p.pair_code, '4F7K');
  assert.deepEqual(settings.getDevice(), { device_id: 'd9', device_token: 'tok-9' });
});

test('pairingStatus: bearer token, keeps the stored token when the relay omits it', async () => {
  paired();
  const calls = stubFetch({ body: { device_id: 'd1', pair_code: '4F7K', claimed: true, worker_name: 'Bay 3' } });
  const p = await client.pairingStatus();
  assert.equal(calls[0].url, 'http://relay.test/v1/devices/me');
  assert.equal(headers(calls[0]).authorization, 'Bearer tok-1');
  assert.equal(p.claimed, true);
  assert.equal(p.device_token, 'tok-1');
});

test('lens routes without a token reject unauthorized without touching the network', async () => {
  settings.setDevice(null);
  const calls = stubFetch({ body: {} });
  await rejects(client.nextAssignment(), 'unauthorized');
  assert.equal(calls.length, 0);
});

test('nextAssignment: 204 -> null; 200 -> assignment with assignment_id on the walkthrough', async () => {
  paired();
  stubFetch({ status: 204 });
  assert.equal(await client.nextAssignment(), null);
  const { walkthrough, ...rest } = mock.fixtures.ASSIGNMENT;
  stubFetch({ body: { ...rest, walkthrough: { ...walkthrough, assignment_id: undefined } } });
  const a = await client.nextAssignment();
  assert.equal(a?.walkthrough.steps.length, 5);
  assert.equal(a?.walkthrough.assignment_id, 'asg-mock-1');
});

test('nextAssignment: 401 drops the token and is not retried; malformed -> bad_request', async () => {
  paired();
  const calls = stubFetch({ status: 401 });
  await rejects(client.nextAssignment(), 'unauthorized');
  assert.equal(calls.length, 1);
  assert.equal(settings.getDevice(), null);
  paired();
  stubFetch({ body: { assignment_id: 'a', walkthrough: { steps: [] } } });
  await rejects(client.nextAssignment(), 'bad_request');
});

test('v2 routes: one retry on 5xx and network errors, none on 4xx', async () => {
  paired();
  let calls = stubFetch({ status: 503 }, { status: 503 });
  await rejects(client.nextAssignment(), 'server_error');
  assert.equal(calls.length, 2);
  calls = stubFetch(new Error('offline'), { status: 204 });
  assert.equal(await client.nextAssignment(), null);
  assert.equal(calls.length, 2);
  calls = stubFetch({ status: 422 });
  await rejects(client.nextAssignment(), 'bad_request');
  assert.equal(calls.length, 1);
});

const ev = (i: number) => ({ assignment_id: 'a1', step_id: `s${i}`, kind: 'step_started' as const, ts: 1000 + i });

test('progress: queued, mirrored to localStorage, flushed as one batch', async () => {
  paired();
  const calls = stubFetch({ body: { accepted: 3 } });
  for (let i = 0; i < 3; i++) client.reportProgress(ev(i));
  assert.equal(calls.length, 0, 'not sent per event');
  assert.equal(JSON.parse(store['specs.progressQueue']).length, 3, 'mirrored for a reload');
  await client.flushProgress();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'http://relay.test/v1/progress');
  assert.equal(headers(calls[0]).authorization, 'Bearer tok-1');
  assert.deepEqual(JSON.parse(calls[0].init.body as string).events, [ev(0), ev(1), ev(2)]);
  assert.equal(client.pendingProgress().length, 0);
  assert.equal(JSON.parse(store['specs.progressQueue']).length, 0);
});

test('progress: the 10th event flushes immediately; the 5 s timer flushes fewer', async () => {
  paired();
  vi.useFakeTimers();
  try {
    let calls = stubFetch({ body: { accepted: 10 } });
    for (let i = 0; i < 10; i++) client.reportProgress(ev(i));
    await vi.advanceTimersByTimeAsync(0);
    assert.equal(calls.length, 1);
    calls = stubFetch({ body: { accepted: 2 } });
    client.reportProgress(ev(20));
    client.reportProgress(ev(21));
    await vi.advanceTimersByTimeAsync(4900);
    assert.equal(calls.length, 0);
    await vi.advanceTimersByTimeAsync(200);
    assert.equal(calls.length, 1);
    assert.equal(JSON.parse(calls[0].init.body as string).events.length, 2);
  } finally {
    vi.useRealTimers();
  }
});

test('progress: 2 min of airplane mode loses nothing and flushes once, no duplicates', async () => {
  paired();
  vi.useFakeTimers();
  try {
    let online = false;
    const received: unknown[] = [];
    let posts = 0;
    (globalThis as any).fetch = async (_url: string, init: RequestInit) => {
      posts++;
      if (!online) throw new TypeError('Failed to fetch');
      received.push(...JSON.parse(init.body as string).events);
      return { ok: true, status: 200, json: async () => ({ accepted: 1 }) };
    };
    for (let i = 0; i < 6; i++) {
      client.reportProgress(ev(100 + i));
      await vi.advanceTimersByTimeAsync(20000); // a step every 20 s, all offline
    }
    assert.equal(received.length, 0);
    assert.equal(client.pendingProgress().length, 6, 'all kept while offline');
    assert.ok(posts < 30, `backoff, not a hot loop (${posts} attempts)`);
    online = true;
    await vi.advanceTimersByTimeAsync(61000); // max backoff
    assert.deepEqual(received, [0, 1, 2, 3, 4, 5].map((i) => ev(100 + i)));
    assert.equal(client.pendingProgress().length, 0);
    await vi.advanceTimersByTimeAsync(60000);
    assert.equal(received.length, 6, 'nothing resent after a successful flush');
  } finally {
    vi.useRealTimers();
  }
});

test('progress: capped at 200 (oldest dropped); a 4xx batch is dropped, not retried forever', async () => {
  paired();
  vi.useFakeTimers();
  try {
    (globalThis as any).fetch = async () => {
      throw new TypeError('offline');
    };
    for (let i = 0; i < 250; i++) client.reportProgress(ev(1000 + i));
    await vi.advanceTimersByTimeAsync(0);
    assert.equal(client.pendingProgress().length, 200);
    assert.equal(client.pendingProgress()[0].step_id, 's1050');
    const calls = stubFetch({ status: 400 });
    await client.flushProgress();
    assert.equal(calls.length, 1);
    assert.equal(client.pendingProgress().length, 0);
  } finally {
    vi.useRealTimers();
  }
});

test('progress survives a reload: a fresh client instance picks up the persisted queue', async () => {
  store['specs.progressQueue'] = JSON.stringify([ev(7), { junk: true }]);
  vi.resetModules();
  const fresh = await import('../src/api/client.ts');
  assert.deepEqual(fresh.pendingProgress(), [ev(7)]);
  store['specs.progressQueue'] = '[]';
});

const tile = mockDiagramImage('dg-sop114-bracket')!;

test('getDiagram: tiles decoded to bytes, cached, concurrent calls share one request', async () => {
  paired();
  const calls = stubFetch({ body: tile });
  const [a, b] = await Promise.all([client.getDiagram('dg-1'), client.getDiagram('dg-1')]);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'http://relay.test/v1/diagrams/dg-1');
  assert.equal(headers(calls[0]).authorization, 'Bearer tok-1');
  assert.equal(a, b);
  assert.deepEqual(a.tiles[0].bytes.slice(0, 8), [137, 80, 78, 71, 13, 10, 26, 10]);
  await client.getDiagram('dg-1');
  assert.equal(calls.length, 1, 'served from cache');
});

test('getDiagram: LRU of 8; 404 -> not_found; malformed tiles -> bad_request; prefetch never goes unhandled', async () => {
  paired();
  let calls = stubFetch({ body: tile });
  for (let i = 0; i < 9; i++) await client.getDiagram(`lru-${i}`);
  await client.getDiagram('lru-0');
  assert.equal(calls.length, 10, 'the oldest was evicted');
  stubFetch({ status: 404 });
  await rejects(client.getDiagram('gone'), 'not_found');
  stubFetch({ body: { diagram_id: 'x', tiles: [{ slot: 0, width: 288, height: 144, image: 'AAAA' }] } });
  await rejects(client.getDiagram('bad'), 'bad_request');
  const packed = Buffer.alloc((288 * 144) / 2).toString('base64');
  stubFetch({ body: { diagram_id: 'p', tiles: [{ slot: 0, width: 288, height: 144, image: packed }] } });
  assert.equal((await client.getDiagram('packed')).tiles[0].bytes.length, 20736, 'packed 4-bit is accepted too');
  calls = stubFetch({ status: 500 });
  void client.getDiagram('prefetch-fails'); // ignored on purpose: must not be an unhandled rejection
  await new Promise((r) => setTimeout(r, 0));
  assert.ok(calls.length >= 1);
});

// --- v2 mocks (what Part 1 lives on under VITE_MOCK=1) --------------------------
test('mock commands: whole-utterance only, every command phrase from BUILD-PLAN-V2 §3', () => {
  const cases: Array<[string, string]> = [
    ['next', 'next'], ['Done.', 'next'], ['next step', 'next'], ['finished', 'next'], ['complete', 'next'],
    ['back', 'back'], ['go back', 'back'], ['previous', 'back'],
    ['repeat', 'repeat'], ['say that again', 'repeat'],
    ['details', 'details'], ['more', 'details'], ['read it', 'details'],
    ['show diagram', 'diagram'], ['diagram', 'diagram'], ['picture', 'diagram'], ['Show me!', 'diagram'],
    ['pause', 'pause'], ['stop task', 'pause'], ['resume', 'resume'], ['continue', 'resume'],
    ['exit', 'exit'], ['close specs', 'exit'],
  ];
  for (const [said, cmd] of cases) {
    const r = mock.mockResponseFor(said);
    assert.equal(r.outcome, 'command', said);
    assert.equal(r.command, cmd, said);
    assert.equal(r.glance, '');
    assert.equal(r.verified, false);
  }
  assert.equal(mock.mockResponseFor("what's the next step's torque").outcome, 'answered', 'a question, not a command');
});

test('mock audio asks hear the queued transcripts in order, then the torque question', async () => {
  mock.setMockDelayMs(0);
  mock.queueMockTranscripts('next', 'show diagram');
  const audio = { format: 'pcm_s16le' as const, sample_rate: 16000 as const, channels: 1 as const, data_b64: 'x' };
  assert.equal((await mock.mockAsk({ session_id: 's', audio })).command, 'next');
  assert.equal((await mock.mockAsk({ session_id: 's', audio })).command, 'diagram');
  assert.equal((await mock.mockAsk({ session_id: 's', audio })).outcome, 'answered');
});

test('mock pairing: code 4F7K, claimed 5 s after the first pair(); then the 5-step task', async () => {
  mock.setMockDelayMs(0);
  mock.resetMockV2();
  let now = 1_000_000;
  const spy = vi.spyOn(Date, 'now').mockImplementation(() => now);
  try {
    const p = await mock.mockPair();
    assert.equal(p.pair_code, '4F7K');
    assert.equal(p.claimed, false);
    assert.equal(await mock.mockNextAssignment(), null, 'nothing before the claim');
    now += 5000;
    const s = await mock.mockPairingStatus();
    assert.equal(s.claimed, true);
    assert.equal(s.worker_name, 'Bay 3');
    const a = (await mock.mockNextAssignment())!;
    const steps = a.walkthrough.steps;
    assert.equal(a.walkthrough.doc_id, 'SOP-114');
    assert.equal(a.walkthrough.revision, 'C');
    assert.ok(Math.abs(Date.parse(a.assigned_at) - new Date().getTime()) < 60_000, 'fresh, or the lens rejects it (12 h TTL)');
    assert.equal(steps.length, 5);
    assert.ok(steps[0].warning && steps[0].warning.length <= 80 && /^[\x20-\x7e]+$/.test(steps[0].warning));
    assert.ok(steps[2].checkpoint && steps[2].checkpoint.length <= 60);
    assert.deepEqual(steps.map((x) => (x.diagram ? 1 : 0)), [0, 1, 1, 0, 0], 'diagrams on steps 2 and 3');
    await mock.mockPostProgress([{ assignment_id: a.assignment_id, step_id: null, kind: 'task_completed', ts: 1 }]);
    await mock.mockPostProgress([{ assignment_id: a.assignment_id, step_id: null, kind: 'task_completed', ts: 1 }]);
    assert.equal(mock.mockProgressLog.length, 1, 'the mock relay de-duplicates like the real one');
    assert.equal(await mock.mockNextAssignment(), null, 'a completed task is not handed out again');
  } finally {
    spy.mockRestore();
    mock.resetMockV2();
  }
});

test('mock diagram tiles: two valid 8-bit grey PNGs, 288x144, every pixel on a lens level', async () => {
  const { inflateSync } = await import('node:zlib');
  mock.setMockDelayMs(0);
  for (const step of mock.fixtures.ASSIGNMENT.walkthrough.steps.filter((s) => s.diagram)) {
    const d = (await mock.mockGetDiagram(step.diagram!.diagram_id))!;
    assert.deepEqual(d.tiles.map((t) => t.slot), [0, 1]);
    let lit = 0;
    for (const t of d.tiles) {
      const png = Buffer.from(t.image, 'base64');
      assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
      assert.equal(png.readUInt32BE(16), 288);
      assert.equal(png.readUInt32BE(20), 144);
      assert.equal(png[24], 8, 'bit depth 8');
      assert.equal(png[25], 0, 'greyscale');
      const idatLen = png.readUInt32BE(33);
      assert.equal(png.toString('ascii', 37, 41), 'IDAT');
      const raw = inflateSync(png.subarray(41, 41 + idatLen)); // also proves the CRC-free zlib stream is valid
      assert.equal(raw.length, 144 * 289);
      for (let y = 0; y < 144; y++) {
        assert.equal(raw[y * 289], 0, 'filter none');
        for (let x = 1; x < 289; x++) {
          const v = raw[y * 289 + x];
          assert.equal(v % 17, 0);
          if (v) lit++;
        }
      }
    }
    assert.ok(lit > 500, `${step.diagram!.diagram_id} draws something (${lit} lit px)`);
  }
  assert.equal(await mock.mockGetDiagram('unknown'), null);
});

test('mock endpoint: speech_end after 1.5 s by default; no_speech returns data_b64 ""', async () => {
  vi.useFakeTimers();
  try {
    const ends: string[] = [];
    await mock.mockStartCapture(() => {}, (r) => ends.push(r));
    await vi.advanceTimersByTimeAsync(1499);
    assert.deepEqual(ends, []);
    await vi.advanceTimersByTimeAsync(1);
    assert.deepEqual(ends, ['speech_end']);
    assert.notEqual((await mock.mockStopCapture()).data_b64, '');
    mock.setMockEndpoint('no_speech');
    await mock.mockStartCapture(() => {}, (r) => ends.push(r));
    await vi.advanceTimersByTimeAsync(3000);
    assert.deepEqual(ends, ['speech_end', 'no_speech']);
    assert.equal((await mock.mockStopCapture()).data_b64, '', 'a mock false trigger sends nothing');
  } finally {
    vi.useRealTimers();
    mock.resetMockV2();
  }
});
