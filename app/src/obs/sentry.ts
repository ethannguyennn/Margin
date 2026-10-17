// Sentry in the WebView: one `ask` transaction with capture / upload / render spans.
// The SDK is loaded dynamically so this module is a no-op until Part 1 adds
// @sentry/browser to app/package.json, and so the tests need no browser.
import { SENTRY_DSN, SESSION_ID } from '../settings.ts';

type SentryApi = {
  init: (o: Record<string, unknown>) => void;
  browserTracingIntegration: () => unknown;
  startSpan: <T>(o: { name: string; op?: string }, cb: () => T) => T;
  setTag: (k: string, v: string) => void;
  captureMessage: (m: string, level?: string) => void;
  captureException: (e: unknown) => void;
};

let sentry: SentryApi | null = null;

/** Call once at boot. Never throws - observability must not break the app. */
export async function initObs(): Promise<boolean> {
  if (sentry) return true;
  if (!SENTRY_DSN) return false;
  try {
    // TS cannot resolve this until Part 1 adds @sentry/browser to app/package.json
    // (dep requested). The import is dynamic so the app runs fine without it.
    const mod = (await import('@sentry/browser')) as unknown as SentryApi;
    mod.init({
      dsn: SENTRY_DSN,
      integrations: [mod.browserTracingIntegration()],
      // browserTracingIntegration patches fetch and attaches sentry-trace /
      // baggage, which is how Part 3 continues the trace server-side.
      tracesSampleRate: 1.0,
      // The Even SDK console.logs every audio event with the raw audioPcm array.
      // Sentry's console breadcrumbs would ship that audio off the device. Drop it.
      beforeBreadcrumb: (b: { category?: string; message?: string }) =>
        b.category === 'console' && b.message?.includes('audioPcm') ? null : b,
      beforeSendLog: (l: { message?: string }) => (l.message?.includes('audioPcm') ? null : l),
      _experiments: { enableLogs: true },
      // Replay deliberately omitted: unproven in the Even WebView, not worth blocking on.
      // TODO(verify-sdk): tunnel: `${RELAY_ORIGIN}/v1/sentry-tunnel` once Part 3 ships the route.
    });
    mod.setTag('session_id', SESSION_ID);
    sentry = mod;
    return true;
  } catch (e) {
    console.warn('[obs] sentry unavailable, continuing without it', e);
    return false;
  }
}

/** One transaction per ask. Wrap Part 1's whole press-to-glance flow in this. */
export function traceAsk<T>(fn: () => Promise<T>): Promise<T> {
  return sentry ? sentry.startSpan({ name: 'ask', op: 'ask' }, fn) : fn();
}

/** Child spans. Budget p50: capture -, upload 300 ms, render 300 ms. */
export function traceSpan<T>(name: 'capture' | 'upload' | 'render', fn: () => T): T {
  return sentry ? sentry.startSpan({ name, op: name }, fn) : fn();
}

export function captureError(code: string, message: string): void {
  console.warn(`[obs] ${code}: ${message}`);
  sentry?.captureMessage(`ask ${code}: ${message}`, 'error');
}

export function captureException(e: unknown): void {
  sentry?.captureException(e);
}
