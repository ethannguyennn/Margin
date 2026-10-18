import { expect, it } from 'vitest';

it('bundles the official SDK APIs used by the existing instrumentation', async () => {
  const sdk = await import('@sentry/browser');
  for (const name of ['init', 'browserTracingIntegration', 'startSpan', 'startNewTrace',
    'startInactiveSpan', 'withActiveSpan', 'getTraceData', 'makeFetchTransport']) {
    expect(typeof sdk[name as keyof typeof sdk], name).toBe('function');
  }
});
