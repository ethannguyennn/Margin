// Run: npm test
import { test } from 'vitest';
import assert from 'node:assert/strict';

process.env.VITE_RELAY_ORIGIN = 'http://relay.test';
process.env.VITE_MOCK = '0';

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

test('generated display survives response validation and is removed on refusal', async () => {
  const display = { kind: 'warning', items: ['Disconnect power.'] };
  stubFetch({ body: { ...ANSWERED, display } });
  assert.deepEqual((await ask(REQ)).display, display);
  stubFetch({ body: { ...ANSWERED, display, verified: false } });
  assert.equal((await ask(REQ)).display, null);
  stubFetch({ body: { ...ANSWERED, display: { kind: 'html', items: ['unsafe'] } } });
  assert.equal((await ask(REQ)).display, null);
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
  const cleaning = mockResponseFor('how do i clean it');
  assert.ok(cleaning.body.includes('60 s') && cleaning.body.length <= 450);
  assert.equal(cleaning.graphic_id, 'housing-cleaning');
  assert.ok(mockResponseFor('torque the M5').body.includes('do not click twice'));
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
