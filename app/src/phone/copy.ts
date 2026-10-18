// Plain-language wording for what the relay and the bridge report. The raw text
// stays available (title attributes, Technical details) for whoever debugs it.

const ERROR_TITLES: Record<string, string> = {
  network: "Can't reach the server",
  timeout: 'The server took too long to answer',
  unauthorized: "This device isn't paired yet",
  rate_limited: 'Too many requests, try again shortly',
  bad_request: "The server couldn't read that request",
};

export function errorTitle(code: string | undefined): string {
  return (code && ERROR_TITLES[code]) || 'Something went wrong';
}

/** A load failure (procedures, steps) as one short sentence. */
export function loadError(raw: string): string {
  if (/VITE_|origin is not set/i.test(raw)) return 'The server address is not configured in this build.';
  if (/fetch|network|unreachable|timed? ?out|abort/i.test(raw)) return "Can't reach the server. Check the connection and try again.";
  return "Couldn't load this right now.";
}

/** The glasses link status in a few words, plus a hint when something is off. */
export function glassesStatus(connected: boolean, raw: string): { label: string; hint: string | null } {
  if (connected) return { label: 'Connected', hint: null };
  if (/error|unable|fail/i.test(raw)) {
    return { label: 'Not connected', hint: 'Open Specs from the Even app with your glasses on to connect them.' };
  }
  return { label: raw.replace(/\.\.\.$/, '…') || 'Not connected', hint: null };
}

export function shortId(id: string): string {
  return id.length > 8 ? `…${id.slice(-6)}` : id;
}

export function clockTime(at: number | string | Date): string {
  return new Date(at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

export function seconds(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}
