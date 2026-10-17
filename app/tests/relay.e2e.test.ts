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
