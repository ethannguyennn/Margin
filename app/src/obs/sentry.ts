// Sentry in the WebView: one `ask` transaction with capture / upload / render spans.
// Verified against @sentry/browser 11.4.0 (logs are on by default in 11.x; no flag).
import { RELAY_ORIGIN, SENTRY_DSN, SESSION_ID, env } from '../settings.ts';
import type { Span } from '@sentry/browser';

let sentry: typeof import('@sentry/browser') | null = null;
/** The ask opened by startAsk(), so upload spans and trace headers attach to it. */
let openAsk: Span | null = null;

/** Call once at boot. Never throws - observability must not break the app. */
export async function initObs(): Promise<boolean> {
  if (sentry) return true;
  if (!SENTRY_DSN) return false;
  try {
    const mod = await import('@sentry/browser');
    mod.init({
      dsn: SENTRY_DSN,
      // No pageload/navigation spans: in a glasses WebView they are noise, and an ask
      // started inside the pageload idle span would be nested under it instead of
      // being its own transaction (seen in the simulator: nothing was ever sent).
      integrations: [mod.browserTracingIntegration({ instrumentPageLoad: false, instrumentNavigation: false })],
      tracesSampleRate: 1.0,
      // Use the page's fetch. Sentry's default borrows a "native" fetch from a throwaway
      // iframe when window.fetch is patched (the Even host patches it); in the simulator
      // WebView that fetch is dead ("global scope is shutting down") and nothing is sent.
      transport: (o) => mod.makeFetchTransport(o, globalThis.fetch.bind(globalThis)),
      // sentry-trace / baggage go to the relay only (Part 3 continues the trace and
      // its CORS allows both). Other origins get no tracing headers.
      tracePropagationTargets: RELAY_ORIGIN ? [RELAY_ORIGIN] : [],
      // One whitelisted origin: route events through the relay once Part 3 ships it.
      ...(env('VITE_SENTRY_TUNNEL') === '1' && RELAY_ORIGIN ? { tunnel: `${RELAY_ORIGIN}/v1/sentry-tunnel` } : {}),
      // The Even SDK console.logs every audio event with the raw audioPcm array.
      // Sentry's console breadcrumbs would ship that audio off the device. Drop it.
      beforeBreadcrumb: (b: { category?: string; message?: string }) =>
        b.category === 'console' && b.message?.includes('audioPcm') ? null : b,
      beforeSendLog: (l) => (l.message?.includes('audioPcm') ? null : l),
      // Replay deliberately omitted: unproven in the Android WebView, not worth blocking on.
    });
    mod.setTag('session_id', SESSION_ID);
    sentry = mod;
    return true;
  } catch (e) {
    console.warn('[obs] sentry unavailable, continuing without it', e);
    return false;
  }
}

/** One transaction - and one trace - per ask. Wrap Part 1's whole press-to-glance flow
 * in this. Without startNewTrace every ask in a session shares the page's trace id. */
export function traceAsk<T>(fn: () => Promise<T>): Promise<T> {
  const s = sentry;
  return s ? s.startNewTrace(() => s.startSpan({ name: 'ask', op: 'ask', forceTransaction: true }, fn)) : fn();
}

/** Part 1's handle-style API (app/src/main.ts ObsModule): startAsk() when the ask is
 * sent, end(outcome) when it resolves. Same transaction/trace rules as traceAsk. */
export function startAsk(): { finishSpan(name: string): void; end(outcome: string): void } {
  const s = sentry;
  if (!s) return { finishSpan() {}, end() {} };
  const t0 = Date.now() / 1000;
  const root = s.startNewTrace(() => s.startInactiveSpan({ name: 'ask', op: 'ask', forceTransaction: true }));
  openAsk = root;
  return {
    // A phase that ran from the start of the ask until now (e.g. 'render').
    finishSpan: (name) => s.startInactiveSpan({ name, op: name, parentSpan: root, startTime: t0 }).end(),
    end: (outcome) => {
      root.setAttribute('outcome', outcome);
      root.end();
      if (openAsk === root) openAsk = null;
    },
  };
}

/** Child spans. Budget p50: upload 300 ms, render 300 ms; end-of-speech to glance <= 3 s. */
export function traceSpan<T>(name: 'capture' | 'upload' | 'render', fn: () => T): T {
  const s = sentry;
  if (!s) return fn();
  return openAsk ? s.withActiveSpan(openAsk, () => s.startSpan({ name, op: name }, fn)) : s.startSpan({ name, op: name }, fn);
}

/** v2 phases outside the press-to-glance ask. startMs is epoch ms when the phase began
 * (omit for an instant marker, e.g. a gesture). Nested under the open ask when there is one. */
export function span(name: 'gesture' | 'endpoint' | 'diagram_fetch', startMs?: number, attrs: Record<string, string> = {}): void {
  const s = sentry;
  if (!s) return;
  const sp = s.startInactiveSpan({
    name,
    op: name,
    ...(startMs ? { startTime: startMs / 1000 } : {}),
    ...(openAsk ? { parentSpan: openAsk } : { forceTransaction: true }),
  });
  for (const [k, v] of Object.entries(attrs)) sp.setAttribute(k, v);
  sp.end();
}

/** sentry-trace + baggage for the current span, set explicitly on the relay call.
 * Not left to fetch auto-instrumentation: in the simulator WebView it never attached
 * them, so the relay started a new trace instead of continuing ours. */
export function traceHeaders(): Record<string, string> {
  const s = sentry;
  if (!s) return {};
  const data = openAsk ? s.withActiveSpan(openAsk, () => s.getTraceData()) : s.getTraceData();
  return { ...(data['sentry-trace'] ? { 'sentry-trace': data['sentry-trace'] } : {}),
    ...(data.baggage ? { baggage: data.baggage } : {}) };
}

export function logAsk(outcome: string, ms: number, traceId: string): void {
  sentry?.logger.info('ask', { outcome, ms, trace_id: traceId });
}

export function captureError(code: string, message: string): void {
  console.warn(`[obs] ${code}: ${message}`);
  sentry?.logger.error(`ask ${code}`, { code, message });
  sentry?.captureMessage(`ask ${code}: ${message}`, 'error');
}

export function captureException(e: unknown): void {
  sentry?.captureException(e);
}
