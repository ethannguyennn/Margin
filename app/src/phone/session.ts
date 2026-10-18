// One session id and one SOP context, held for the phone. Persisted in localStorage
// so a reload keeps asking under the same session and the relay's "repeat" memory
// still holds the last answer. (Linked to the glasses, the lens session wins: store.tsx.)
import type { AskResponse } from './contract';
import { getMicSource, uuid, type MicSource } from '../settings';

export { uuid, type MicSource };

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

export const NO_CONTEXT: StepContext = { doc_id: null, step_id: null };

export function newSession(sessionId: string): SessionState {
  return {
    sessionId,
    context: NO_CONTEXT,
    listening: false,
    micSource: getMicSource(), // the persisted setting audio/capture.ts reads
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
      micSource: fresh.micSource,
      listening: false,
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
