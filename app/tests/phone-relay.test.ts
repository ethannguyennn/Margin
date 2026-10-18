// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.resetModules(); });

it('serves every phone route offline from the same mock catalog as the lens', async () => {
  vi.stubEnv('VITE_MOCK', '1'); vi.stubEnv('VITE_RELAY_ORIGIN', ''); vi.resetModules();
  const fetcher = vi.fn(() => { throw new Error('Mock mode must never call fetch'); });
  vi.stubGlobal('fetch', fetcher);
  const mocks = await import('../src/mock'); mocks.setMockDelayMs(0);
  const relay = await import('../src/phone/relay');
  expect(await relay.health('session')).toMatchObject({ mock: true, db: 'mock' });
  const [procedure] = await relay.listProcedures('session');
  expect(procedure.doc_id).toBe(mocks.fixtures.ASSIGNMENT.walkthrough.doc_id);
  const steps = await relay.listSteps('session', procedure.doc_id, procedure.revision);
  expect(steps).toEqual(mocks.fixtures.ASSIGNMENT.walkthrough.steps);
  steps[0].body = 'Changed in the caller';
  expect((await relay.listSteps('session', procedure.doc_id, procedure.revision))[0].body).not.toBe(steps[0].body);
  expect(await relay.listSteps('session', procedure.doc_id, 'UNKNOWN')).toEqual([]);
  const context = { doc_id: null, step_id: null };
  expect((await relay.ask('session', 'how tight is the m5', context)).verified).toBe(true);
  expect(await relay.logDeviation('session', 'synthetic deviation', context)).toMatchObject({ notified: true });
  expect(fetcher).not.toHaveBeenCalled();
});

it('keeps live mode on the configured relay', async () => {
  vi.stubEnv('VITE_MOCK', '0'); vi.stubEnv('VITE_RELAY_ORIGIN', 'https://relay.test'); vi.resetModules();
  const fetcher = vi.fn(async () => new Response('[]', { headers: { 'content-type': 'application/json' } }));
  vi.stubGlobal('fetch', fetcher);
  const relay = await import('../src/phone/relay');
  await expect(relay.listProcedures('session')).resolves.toEqual([]);
  expect(fetcher).toHaveBeenCalledWith('https://relay.test/v1/procedures', expect.anything());
});
