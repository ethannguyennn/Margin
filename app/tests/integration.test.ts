// Real HTTP, real sockets, real abort - against a stub relay that speaks the
// frozen contract. This is NOT Part 3's relay; swap VITE_RELAY_ORIGIN for theirs
// (MOCK_MODE=1) and the same assertions should hold.
// Run: npm test (or npx vitest run tests/integration.test.ts)
import { afterAll, test, vi } from 'vitest';
import assert from 'node:assert/strict';
import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';

const seen: Array<{ url: string; sessionId?: string; body: any }> = [];

function makeRelay(): Promise<Server> {
  const srv = createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString()) : null;
      seen.push({ url: req.url!, sessionId: req.headers['x-session-id'] as string, body });
      const json = (status: number, payload: unknown) => {
        res.writeHead(status, { 'content-type': 'application/json' });
        res.end(JSON.stringify(payload));
      };
      if (req.url === '/v1/health') return json(200, { ok: true, mock: true, db: 'sqlite', version: 'stub-1' });
      if (body?.text === 'hang') return; // never answers: exercises the timeout
      if (req.url !== '/v1/ask') return json(404, { trace_id: '', outcome: 'error', error: { code: 'bad_request', message: 'no route' } });
      if (body?.text === 'boom') return json(500, { trace_id: 'tr-boom', outcome: 'error', error: { code: 'llm_timeout', message: 'model timed out' } });
      return json(200, {
        trace_id: 'tr-1',
        transcript: body?.text ?? 'transcribed audio',
        intent: 'question',
        outcome: 'answered',
        glance: 'Step 4.2: torque M5 to 4 N-m',
        body: 'Torque all four M5 bracket screws to 4 N-m.',
        source: 'SOP-114 Sec 4.2 rev C',
        citations: [{ chunk_id: 'SOP-114:C:4.2', doc_id: 'SOP-114', revision: 'C', section: '4.2', quote: 'Torque ... 4 N-m' }],
        verified: true,
        walkthrough: null,
        latency_ms: { stt: 410, embed: 80, retrieve: 150, generate: 900, verify: 20, total: 1560 },
      });
    });
  });
  return new Promise((resolve) => srv.listen(0, '127.0.0.1', () => resolve(srv)));
}

let relay = await makeRelay();
const port = (relay.address() as AddressInfo).port;
process.env.VITE_RELAY_ORIGIN = `http://127.0.0.1:${port}`;
process.env.VITE_MOCK = '0';
process.env.VITE_ASK_TIMEOUT_MS = '500'; // the 8 s contract timeout, shortened for the test

const { ask, health, logDeviation } = await import('../src/api/client.ts');

test('health reaches the relay', async () => {
  const h = await health();
  assert.deepEqual(h, { ok: true, mock: true, db: 'sqlite', version: 'stub-1' });
});

test('ask sends the contract body with x-session-id and renders an answer', async () => {
  const res = await ask({
    session_id: 'ignored-by-client',
    audio: { format: 'pcm_s16le', sample_rate: 16000, channels: 1, data_b64: 'AAA=' },
    text: null,
    context: { doc_id: null, step_id: null },
  });
  assert.equal(res.outcome, 'answered');
  assert.equal(res.verified, true);
  assert.ok(res.citations.length > 0);
  const last = seen.at(-1)!;
  assert.equal(last.url, '/v1/ask');
  assert.ok(last.sessionId, 'x-session-id must be present');
  assert.equal(last.body.audio.format, 'pcm_s16le');
  assert.equal(last.body.audio.sample_rate, 16000);
});

test('a relay that never answers times out and is not retried', async () => {
  const before = seen.length;
  const t0 = Date.now();
  const res = await ask({ session_id: 's', text: 'hang' });
  assert.equal(res.error?.code, 'timeout');
  assert.equal(seen.length - before, 1, 'a timeout must not be retried');
  assert.ok(Date.now() - t0 < 2000);
});

test('a 5xx with a relay error body is retried once and surfaces the relay code', async () => {
  const before = seen.length;
  const res = await ask({ session_id: 's', text: 'boom' });
  assert.equal(seen.length - before, 2, 'exactly one retry');
  assert.equal(res.outcome, 'error');
  assert.equal(res.error?.code, 'llm_timeout');
});

test('killed relay produces the ERROR outcome, and the next press retries cleanly', async () => {
  await new Promise((r) => relay.close(r));
  const dead = await ask({ session_id: 's', text: 'how tight is the m5' });
  assert.equal(dead.outcome, 'error');
  assert.equal(dead.error?.code, 'network');

  // Same port, relay back up: the next press must just work.
  relay = await new Promise((resolve) => {
    const s = createServer((_req, res) => {
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(
        JSON.stringify({
          trace_id: 'tr-2',
          transcript: 'how tight is the m5',
          intent: 'question',
          outcome: 'answered',
          glance: 'Step 4.2: torque M5 to 4 N-m',
          body: 'Torque to 4 N-m.',
          source: 'SOP-114 Sec 4.2 rev C',
          citations: [{ chunk_id: 'SOP-114:C:4.2', doc_id: 'SOP-114', revision: 'C', section: '4.2', quote: 'q' }],
          verified: true,
          walkthrough: null,
          latency_ms: { stt: 0, embed: 0, retrieve: 0, generate: 0, verify: 0, total: 0 },
        }),
      );
    });
    s.listen(port, '127.0.0.1', () => resolve(s));
  });
  const live = await ask({ session_id: 's', text: 'how tight is the m5' });
  assert.equal(live.outcome, 'answered');
  assert.equal(live.trace_id, 'tr-2');
});

test('deviation logging posts to /v1/deviation', async () => {
  await new Promise((r) => relay.close(r));
  relay = await new Promise((resolve) => {
    const s = createServer((req, res) => {
      seen.push({ url: req.url!, sessionId: req.headers['x-session-id'] as string, body: null });
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ deviation_id: 'dev-7', notified: true }));
    });
    s.listen(port, '127.0.0.1', () => resolve(s));
  });
  const out = await logDeviation('bracket arrived pre-drilled', { doc_id: 'SOP-114', step_id: 'SOP-114:C:4.2' });
  assert.deepEqual(out, { deviation_id: 'dev-7', notified: true });
  assert.equal(seen.at(-1)!.url, '/v1/deviation');
  afterAll(() => relay.close());
});

test('production tracing loads the real SDK and creates a fresh trace for each ask', async () => {
  vi.resetModules();
  vi.stubEnv('VITE_SENTRY_DSN', 'https://public@o0.ingest.sentry.io/1');
  vi.stubEnv('VITE_SENTRY_TUNNEL', '0');
  vi.stubGlobal('fetch', async () => new Response('', { status: 200 }));
  const sdk = await import('@sentry/browser');
  try {
    const obs = await import('../src/obs/sentry.ts');
    assert.equal(await obs.initObs(), true);
    const first = obs.startAsk();
    const a = obs.traceSpan('upload', () => obs.traceHeaders());
    first.end('answered');
    const second = obs.startAsk();
    const b = obs.traceSpan('upload', () => obs.traceHeaders());
    second.end('answered');
    assert.match(a['sentry-trace'], /^[0-9a-f]{32}-[0-9a-f]{16}-[01]$/);
    assert.notEqual(a['sentry-trace'].slice(0, 32), b['sentry-trace'].slice(0, 32));
    const options = sdk.getClient()!.getOptions();
    assert.equal(options.beforeBreadcrumb!({ category: 'console', message: 'audioPcm: private' }, {}), null);
    assert.equal(options.beforeSendLog!({ message: 'audioPcm: private' } as never, {}), null);
  } finally {
    await sdk.close(1000);
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  }
});
