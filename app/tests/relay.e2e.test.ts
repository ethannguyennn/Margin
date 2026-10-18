// Contract check against a REAL relay (Part 3), not a stub. Skipped unless pointed at one:
//   MARGIN_E2E_RELAY=http://127.0.0.1:8080 npx vitest run tests/relay.e2e.test.ts
// Start Part 3's relay first: MOCK_MODE=1 ALLOWED_ORIGINS=http://localhost:5174 \
//   uvicorn margin_relay.main:create_app --factory --port 8080
import { describe, test } from 'vitest';
import assert from 'node:assert/strict';

const RELAY = process.env.MARGIN_E2E_RELAY;
process.env.VITE_RELAY_ORIGIN = RELAY ?? 'http://unused.invalid';
process.env.VITE_MOCK = '0';

const { ask, health, logDeviation } = await import('../src/api/client.ts');
const { uuid } = await import('../src/settings.ts');

// 1 s of a 440 Hz tone, pcm_s16le mono 16 kHz - real bytes over the wire.
function tone(): string {
  const n = 16000;
  const buf = Buffer.alloc(n * 2);
  for (let i = 0; i < n; i++) buf.writeInt16LE(Math.round(8000 * Math.sin((2 * Math.PI * 440 * i) / 16000)), i * 2);
  return buf.toString('base64');
}

describe.skipIf(!RELAY)('real relay contract', () => {
  test('health', async () => {
    const h = await health();
    assert.equal(h.ok, true, JSON.stringify(h));
    console.info('[e2e] health', h);
  });

  test('text ask comes back as a valid contract response', async () => {
    const res = await ask({ session_id: uuid(), text: 'how tight is the m5 on the mounting bracket', context: { doc_id: null, step_id: null } });
    console.info('[e2e] text ->', res.outcome, res.glance, res.source, res.trace_id);
    assert.notEqual(res.outcome, 'error', JSON.stringify(res.error));
    assert.ok(res.trace_id);
    if (res.outcome === 'answered') assert.ok(res.verified && res.citations.length > 0);
  });

  test('audio ask (real PCM bytes) is accepted', async () => {
    const res = await ask({
      session_id: uuid(),
      audio: { format: 'pcm_s16le', sample_rate: 16000, channels: 1, data_b64: tone() },
      text: null,
      context: { doc_id: null, step_id: null },
    });
    console.info('[e2e] audio ->', res.outcome, JSON.stringify(res.transcript), res.error?.code ?? '');
    assert.notEqual(res.error?.code, 'bad_request', JSON.stringify(res.error));
  });

  test('a contract violation surfaces as bad_request, not a crash', async () => {
    const res = await ask({ session_id: 'not-a-uuid', text: 'torque' });
    assert.equal(res.outcome, 'error');
    assert.equal(res.error?.code, 'bad_request');
  });

  test('deviation is logged', async () => {
    const out = await logDeviation('bracket arrived pre-drilled', { doc_id: 'SOP-114', step_id: 'SOP-114:C:4.2' });
    console.info('[e2e] deviation', out);
    assert.ok(out.deviation_id, JSON.stringify(out));
  });

  test('CORS preflight allows the headers the app sends', async () => {
    const res = await fetch(`${RELAY}/v1/ask`, {
      method: 'OPTIONS',
      headers: {
        Origin: 'http://localhost:5174',
        'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'content-type,x-session-id,sentry-trace,baggage',
      },
    });
    const allowed = (res.headers.get('access-control-allow-headers') ?? '').toLowerCase();
    for (const h of ['content-type', 'x-session-id', 'sentry-trace', 'baggage']) assert.ok(allowed.includes(h), `${h} not allowed: ${allowed}`);
  });
});

// --- v2 lens routes against Part 3's relay (MOCK_MODE=1 with PORTAL_TOKEN set) ---------
// MARGIN_E2E_PORTAL_TOKEN=<the relay's PORTAL_TOKEN> drives the supervisor side (claim, assign, board).
const PORTAL = process.env.MARGIN_E2E_PORTAL_TOKEN;
describe.skipIf(!RELAY || !PORTAL)('real relay contract v2 (client v2)', () => {
  const store: Record<string, string> = {};
  (globalThis as any).localStorage ??= {
    getItem: (k: string) => store[k] ?? null,
    setItem: (k: string, v: string) => void (store[k] = String(v)),
    removeItem: (k: string) => void delete store[k],
  };
  const portal = async (method: string, path: string, body?: unknown) => {
    const res = await fetch(`${RELAY}${path}`, {
      method,
      headers: { authorization: `Bearer ${PORTAL}`, ...(body ? { 'content-type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    assert.ok(res.ok, `${method} ${path}: HTTP ${res.status} ${await res.clone().text()}`);
    return res.json();
  };
  const ctx: { device_id?: string; assignment_id?: string; step_id?: string; diagram_id?: string } = {};

  test('pair -> unclaimed -> supervisor claims -> claimed', async () => {
    const client = await import('../src/api/client.ts');
    const p = await client.pair();
    assert.ok(p.device_token && p.pair_code, JSON.stringify(p));
    ctx.device_id = p.device_id;
    assert.equal((await client.pairingStatus()).claimed, false);
    await portal('POST', '/v1/devices/claim', { pair_code: p.pair_code, worker_name: 'Bay 3' });
    const me = await client.pairingStatus();
    assert.equal(me.claimed, true);
    assert.equal(me.worker_name, 'Bay 3');
  });

  test('no task -> 204 -> null; assigned -> the walkthrough arrives', async () => {
    const client = await import('../src/api/client.ts');
    assert.equal(await client.nextAssignment(), null);
    await portal('POST', '/v1/assignments', { device_id: ctx.device_id, doc_id: 'SOP-114', revision: 'C' });
    const a = await client.nextAssignment();
    assert.ok(a, 'assignment');
    assert.equal(a!.walkthrough.doc_id, 'SOP-114');
    assert.equal(a!.walkthrough.assignment_id, a!.assignment_id);
    ctx.assignment_id = a!.assignment_id;
    const withDiagram = a!.walkthrough.steps.find((s) => s.diagram);
    ctx.step_id = withDiagram?.step_id ?? a!.walkthrough.steps[0].step_id;
    ctx.diagram_id = withDiagram?.diagram?.diagram_id;
    console.info(`[e2e] assignment ${a!.assignment_id}: ${a!.walkthrough.steps.length} steps, diagram ${ctx.diagram_id}`);
  });

  test('the step diagram arrives as two decoded PNG tiles, cached', async () => {
    const client = await import('../src/api/client.ts');
    assert.ok(ctx.diagram_id, 'the mock relay serves one approved diagram on SOP-114 4.2');
    const d = await client.getDiagram(ctx.diagram_id!);
    assert.deepEqual(d.tiles.map((t) => [t.slot, t.width, t.height]), [[0, 288, 144], [1, 288, 144]]);
    for (const t of d.tiles) assert.deepEqual(t.bytes.slice(0, 4), [137, 80, 78, 71], 'PNG');
    assert.equal(await client.getDiagram(ctx.diagram_id!), d, 'second call is the cache');
  });

  test('progress batch lands on the board; resending it does not duplicate', async () => {
    const client = await import('../src/api/client.ts');
    const t0 = Date.now();
    const events = [
      { assignment_id: ctx.assignment_id!, step_id: null, kind: 'task_started' as const, ts: t0 },
      { assignment_id: ctx.assignment_id!, step_id: ctx.step_id!, kind: 'step_started' as const, ts: t0 + 1 },
    ];
    for (const e of events) client.reportProgress(e);
    await client.flushProgress();
    assert.equal(client.pendingProgress().length, 0);
    const rows = async () => ((await portal('GET', '/v1/progress?since=0')) as Array<{ assignment_id: string }>).filter((r) => r.assignment_id === ctx.assignment_id);
    const before = await rows();
    assert.ok(before.length >= 1, 'board shows the task');
    for (const e of events) client.reportProgress(e); // a retry after a lost response
    await client.flushProgress();
    assert.deepEqual(await rows(), before, 'idempotent on (assignment_id, step_id, kind, ts)');
  });

  test('"next" inside the task takes the command fast path', async () => {
    const res = await ask({ session_id: uuid(), text: 'next', context: { doc_id: 'SOP-114', step_id: ctx.step_id!, assignment_id: ctx.assignment_id } });
    assert.equal(res.outcome, 'command', JSON.stringify(res));
    assert.equal(res.command, 'next');
    assert.equal(res.glance, '');
  });

  test('a rejected token is dropped (401) and the next call says unauthorized', async () => {
    const client = await import('../src/api/client.ts');
    const settings = await import('../src/settings.ts');
    settings.setDevice({ device_id: ctx.device_id!, device_token: 'not-a-real-token' });
    await assert.rejects(client.nextAssignment(), (e: any) => e.code === 'unauthorized' && e.status === 401);
    assert.equal(settings.getDevice(), null);
    await assert.rejects(client.nextAssignment(), (e: any) => e.code === 'unauthorized');
  });
});
