// One session id and one SOP context, held for the phone. Persisted in localStorage
// so a reload keeps asking under the same session and the relay's "repeat" memory
// still holds the last answer.
import type { AskResponse } from './contract';

export type MicSource = 'glasses' | 'phone';

/** What the lens asks with: a procedure, optionally pinned to one step. */
export interface StepContext {
  doc_id: string | null;
  step_id: string | null;
}

export interface Exchange {
  at: number;
  question: string;
  intent: string;
  outcome: string;
  glance: string;
  trace_id: string;
}

export interface SessionState {
  sessionId: string;
  context: StepContext;
  listening: boolean;
  micSource: MicSource;
  lastAnswer: AskResponse | null;
  history: Exchange[];
}

const KEY = 'margin.companion.session';
export const HISTORY_MAX = 20;

/** The relay validates session_id as a UUID, so the fallback must be one too:
 * randomUUID only exists in secure contexts, getRandomValues everywhere. */
export function uuid(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const b = globalThis.crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40; // version 4
  b[8] = (b[8] & 0x3f) | 0x80; // RFC 4122 variant
  const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

export const NO_CONTEXT: StepContext = { doc_id: null, step_id: null };

export function newSession(sessionId: string): SessionState {
  return {
    sessionId,
    context: NO_CONTEXT,
    listening: false,
    micSource: 'glasses',
    lastAnswer: null,
    history: [],
  };
}

export function loadSession(): SessionState {
  const fresh = newSession(uuid());
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return fresh;
    const saved = JSON.parse(raw) as Partial<SessionState>;
    return {
      ...fresh,
      ...saved,
      sessionId: typeof saved.sessionId === 'string' && saved.sessionId ? saved.sessionId : fresh.sessionId,
      context: { ...NO_CONTEXT, ...(saved.context ?? {}) },
      history: Array.isArray(saved.history) ? saved.history.slice(0, HISTORY_MAX) : [],
    };
  } catch {
    return fresh; // storage blocked: the session just will not survive a reload
  }
}

export function saveSession(s: SessionState): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* non-fatal: the session just will not survive a reload */
  }
}
