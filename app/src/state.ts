import type { AskRequest, AskResponse, Walkthrough } from './types';
import { sanitizeForG2 } from './ui/glyphs';
import { BODY_PAGE_CHARS, paginate } from './ui/paginate';
import { parseDisplay, displayPages } from './ui/generated-display';
import { answerGraphic, stepGraphic, ILLUSTRATED_PAGE_CHARS } from './ui/sop-graphics';

export const GLANCE_TIMEOUT_MS = 20_000;
export const INACTIVITY_TIMEOUT_MS = 60_000;
export const WALKTHROUGH_TTL_MS = 30 * 60_000;
export const STORAGE_KEY = 'margin.session.v1';
export type Screen = 'PRIVACY' | 'IDLE' | 'LISTENING' | 'THINKING' | 'ANSWER_GLANCE' |
  'ANSWER_EXPANDED' | 'NOT_FOUND' | 'WALKTHROUGH' | 'LOGGED' | 'ERROR';
export type Gesture = 'PRESS' | 'DOUBLE_PRESS' | 'UP' | 'DOWN' | 'LONG_PRESS';
export type Action = { type: Gesture | 'TIMEOUT' | 'DISMISS' } |
  { type: 'RESPONSE'; response: AskResponse; now: number } |
  { type: 'FAIL' } |
  // A question typed on the phone screen: same THINKING -> answer path as speech.
  { type: 'TEXT_ASK' };
export type Effect = 'START_CAPTURE' | 'STOP_AND_SEND' | 'SEND_TEXT' | 'CANCEL' | 'EXIT';
export interface AskContext { doc_id: string | null; step_id: string | null; }
export interface LensState {
  screen: Screen;
  session_id: string;
  privacySeen: boolean;
  micSource: 'glasses' | 'phone';
  response: AskResponse | null;
  walkthrough: Walkthrough | null;
  walkthroughReceivedAt: number;
  pages: string[];
  page: number;
  detailReturn: 'ANSWER_GLANCE' | 'WALKTHROUGH';
}
export interface Transition { state: LensState; effects: Effect[]; }

export function initialState(sessionId: string): LensState {
  return { screen: 'PRIVACY', session_id: sessionId, privacySeen: false,
    micSource: 'glasses', response: null, walkthrough: null, walkthroughReceivedAt: 0,
    pages: [''], page: 0, detailReturn: 'ANSWER_GLANCE' };
}

function idle(state: LensState): LensState {
  return { ...state, screen: 'IDLE', response: null, walkthrough: null,
    walkthroughReceivedAt: 0, pages: [''], page: 0, detailReturn: 'ANSWER_GLANCE' };
}
function failed(state: LensState): LensState {
  return { ...idle(state), screen: 'ERROR' };
}

export function validWalkthrough(value: unknown): value is Walkthrough {
  if (!value || typeof value !== 'object') return false;
  const w = value as Walkthrough;
  return typeof w.doc_id === 'string' && w.doc_id.length > 0 && typeof w.revision === 'string' &&
    typeof w.title === 'string' && Array.isArray(w.steps) && w.steps.length > 0 &&
    w.steps.length === w.total && Number.isInteger(w.index) && w.index >= 0 && w.index < w.total &&
    w.steps.every(s => s && [s.step_id, s.label, s.glance, s.body].every(v => typeof v === 'string') &&
      s.glance.length > 0 && s.body.length > 0);
}

function receive(state: LensState, response: AskResponse, now: number): LensState {
  // Fail closed, before inspecting or rendering any model-provided answer text.
  if (response.outcome === 'not_found') return { ...idle(state), screen: 'NOT_FOUND' };
  if (response.outcome === 'error') return failed(state);
  if (response.verified !== true) return failed(state);
  try {
    if (response.walkthrough !== null) {
      if (!validWalkthrough(response.walkthrough)) return failed(state);
      // Preflight every step locally. Swiping will never fetch more data.
      response.walkthrough.steps.forEach(step => paginate(sanitizeForG2(step.body),
        stepGraphic(step) ? ILLUSTRATED_PAGE_CHARS : BODY_PAGE_CHARS));
      return { ...state, screen: 'WALKTHROUGH', response,
        walkthrough: structuredClone(response.walkthrough), walkthroughReceivedAt: now, page: 0 };
    }
    if (response.outcome === 'logged') return { ...idle(state), screen: 'LOGGED' };
    if (response.outcome !== 'answered' || !response.glance?.trim() || !response.body?.trim()) return failed(state);
    const display = parseDisplay(response.display);
    const card = display && display.kind !== 'answer' ? display : null;
    const budget = answerGraphic(response) ? ILLUSTRATED_PAGE_CHARS : BODY_PAGE_CHARS;
    const pages = [
      ...displayPages(card, budget),
      ...paginate(sanitizeForG2(response.body), budget),
    ];
    return { ...idle(state), screen: card ? 'ANSWER_EXPANDED' : 'ANSWER_GLANCE',
      response: { ...response, display }, pages };
  } catch {
    return failed(state);
  }
}

/** All control flow is pure and independent of the SDK/audio/network. */
export function transition(state: LensState, action: Action): Transition {
  const done = (next = state, effects: Effect[] = []): Transition => ({ state: next, effects });
  if (action.type === 'TIMEOUT' || action.type === 'DISMISS') return done(idle(state), ['CANCEL']);
  if (action.type === 'LONG_PRESS') return done();
  if (action.type === 'FAIL') return done(failed(state), ['CANCEL']);
  if (action.type === 'RESPONSE') return state.screen === 'THINKING' ? done(receive(state, action.response, action.now)) : done();
  if (action.type === 'TEXT_ASK') {
    // One question in flight at a time; the privacy notice must be acknowledged on the
    // glasses first. From LISTENING the open mic is cancelled before the text is sent.
    if (state.screen === 'THINKING' || state.screen === 'PRIVACY') return done();
    return done({ ...idle(state), screen: 'THINKING' }, ['CANCEL', 'SEND_TEXT']);
  }

  if (action.type === 'DOUBLE_PRESS') {
    if (state.screen === 'IDLE' || state.screen === 'PRIVACY') return done(state, ['EXIT']);
    if (state.screen === 'ANSWER_EXPANDED') return done({ ...state, screen: state.detailReturn, page: 0 });
    return done(idle(state), ['CANCEL']);
  }
  if (action.type === 'UP' || action.type === 'DOWN') {
    const delta = action.type === 'UP' ? -1 : 1;
    if (state.screen === 'ANSWER_EXPANDED') return done({ ...state, page: Math.max(0, Math.min(state.pages.length - 1, state.page + delta)) });
    if (state.screen === 'WALKTHROUGH' && state.walkthrough) {
      return done({ ...state, walkthrough: { ...state.walkthrough,
        index: Math.max(0, Math.min(state.walkthrough.total - 1, state.walkthrough.index + delta)) } });
    }
    return done();
  }
  switch (state.screen) {
    case 'PRIVACY': return done({ ...idle(state), privacySeen: true });
    case 'IDLE':
    case 'NOT_FOUND':
    case 'ERROR': return done({ ...idle(state), screen: 'LISTENING' }, ['START_CAPTURE']);
    case 'LISTENING': return done({ ...state, screen: 'THINKING' }, ['STOP_AND_SEND']);
    case 'ANSWER_GLANCE': return done({ ...state, screen: 'ANSWER_EXPANDED', page: 0, detailReturn: 'ANSWER_GLANCE' });
    case 'ANSWER_EXPANDED': return done({ ...state, screen: state.detailReturn, page: 0 });
    case 'WALKTHROUGH': {
      const step = state.walkthrough?.steps[state.walkthrough.index];
      if (!step) return done(failed(state));
      return done({ ...state, screen: 'ANSWER_EXPANDED', detailReturn: 'WALKTHROUGH', page: 0,
        pages: paginate(sanitizeForG2(step.body), stepGraphic(step) ? ILLUSTRATED_PAGE_CHARS : BODY_PAGE_CHARS) });
    }
    case 'LOGGED': return done(idle(state));
    case 'THINKING': return done();
  }
}

interface StoredSession {
  version: 1;
  session_id: string;
  privacySeen: boolean;
  micSource: 'glasses' | 'phone';
  walkthrough: Walkthrough | null;
  walkthroughReceivedAt: number;
}

/** Store no audio and no ordinary answer/transcript. Walkthrough steps are text. */
export function serializeSession(state: LensState): string {
  const stored: StoredSession = { version: 1, session_id: state.session_id,
    privacySeen: state.privacySeen, micSource: state.micSource,
    walkthrough: state.walkthrough, walkthroughReceivedAt: state.walkthroughReceivedAt };
  return JSON.stringify(stored);
}

export function restoreSession(raw: string, now: number, newSessionId: string): LensState {
  const fresh = initialState(newSessionId);
  try {
    const saved = JSON.parse(raw) as StoredSession;
    if (!saved || saved.version !== 1) return fresh;
    const state = { ...fresh,
      session_id: typeof saved.session_id === 'string' && saved.session_id ? saved.session_id : newSessionId,
      privacySeen: saved.privacySeen === true,
      micSource: saved.micSource === 'phone' ? 'phone' as const : 'glasses' as const };
    state.screen = state.privacySeen ? 'IDLE' : 'PRIVACY';
    const age = now - saved.walkthroughReceivedAt;
    if (state.privacySeen && typeof saved.walkthroughReceivedAt === 'number' && age >= 0 && age < WALKTHROUGH_TTL_MS && validWalkthrough(saved.walkthrough)) {
      try { saved.walkthrough.steps.forEach(step => paginate(sanitizeForG2(step.body),
        stepGraphic(step) ? ILLUSTRATED_PAGE_CHARS : BODY_PAGE_CHARS)); }
      catch { return state; }
      return { ...state, screen: 'WALKTHROUGH', walkthrough: saved.walkthrough,
        walkthroughReceivedAt: saved.walkthroughReceivedAt };
    }
    return state;
  } catch { return fresh; }
}

export function timeoutFor(state: LensState): number | null {
  if (state.screen === 'PRIVACY' || state.screen === 'IDLE' || state.screen === 'WALKTHROUGH' ||
    (state.screen === 'ANSWER_EXPANDED' && state.detailReturn === 'WALKTHROUGH')) return null;
  return state.screen === 'ANSWER_GLANCE' ? GLANCE_TIMEOUT_MS : INACTIVITY_TIMEOUT_MS;
}

export interface LensPorts {
  startCapture(onLevel: (level: number) => void): Promise<void>;
  stopCapture(): Promise<{ data_b64: string; sample_rate: 16000 }>;
  ask(request: AskRequest, opts?: { signal?: AbortSignal }): Promise<AskResponse>;
  render(state: LensState, level: number): Promise<void>;
  persist(state: LensState): Promise<void>;
  exit(): Promise<void>;
  now(): number;
  onError(error: unknown): void;
}

/** Coordinates asynchronous effects independently of Part 2 and the SDK. */
export class LensController {
  state: LensState;
  private epoch = 0;
  private request: AbortController | null = null;
  private capture: Promise<void> = Promise.resolve();
  private timer: ReturnType<typeof setTimeout> | undefined;
  private deadline = 0;
  private disposed = false;
  private suspended = false;
  private level = 0;
  private pendingText: { text: string; context: AskContext } | null = null;
  constructor(state: LensState, private readonly ports: LensPorts) { this.state = state; }
  async start(): Promise<void> { await this.ports.render(this.state, this.level); this.armTimer(); }
  /** Ask a typed question (from the phone screen). False when one is already in flight
   * or the privacy notice has not been acknowledged yet. */
  askText(text: string, context: AskContext = { doc_id: null, step_id: null }): boolean {
    const question = text.trim();
    if (this.disposed || !question || this.state.screen === 'THINKING' || this.state.screen === 'PRIVACY') return false;
    this.pendingText = { text: question, context };
    this.dispatch({ type: 'TEXT_ASK' });
    return true;
  }
  dispatch(action: Action): void {
    if (this.disposed) return;
    const { state, effects } = transition(this.state, action);
    if (state !== this.state) {
      this.state = state; this.level = 0;
      void this.ports.render(state, this.level).catch(this.ports.onError);
      void this.ports.persist(state).catch(this.ports.onError);
      this.armTimer();
    }
    for (const effect of effects) this.effect(effect);
  }
  private armTimer(): void {
    clearTimeout(this.timer);
    const ms = timeoutFor(this.state);
    this.deadline = ms === null ? 0 : this.ports.now() + ms;
    if (ms !== null && !this.suspended) this.timer = setTimeout(() => this.dispatch({ type: 'TIMEOUT' }), ms);
  }
  private effect(effect: Effect): void {
    if (effect === 'EXIT') {
      // Keep handlers active if the user cancels native exit confirmation.
      void this.ports.persist(this.state).then(() => this.ports.exit()).catch(this.ports.onError);
      return;
    }
    if (effect === 'CANCEL') {
      this.epoch += 1; this.request?.abort(); this.request = null;
      this.capture = this.capture.then(async () => { await this.ports.stopCapture(); }).catch(this.ports.onError);
      return;
    }
    if (effect === 'START_CAPTURE') {
      const epoch = ++this.epoch;
      this.request?.abort();
      this.capture = this.capture.then(() => {
        if (this.epoch !== epoch || this.disposed) return;
        return this.ports.startCapture(level => {
        if (this.epoch !== epoch || this.state.screen !== 'LISTENING' || this.suspended) return;
        this.level = level;
        void this.ports.render(this.state, level).catch(this.ports.onError);
        });
      }).catch(error => {
        this.ports.onError(error);
        if (epoch === this.epoch && !this.disposed) this.dispatch({ type: 'FAIL' });
      });
      return;
    }
    if (effect === 'SEND_TEXT') {
      const pending = this.pendingText; this.pendingText = null;
      if (!pending) return;
      const epoch = this.epoch;
      const request = new AbortController(); this.request = request;
      const req: AskRequest = { session_id: this.state.session_id, text: pending.text,
        revision: null, context: pending.context };
      // Queued behind the cancelled capture so the mic is closed before the ask goes out.
      this.capture = this.capture.then(() => {
        if (epoch !== this.epoch || this.disposed) return;
        void this.ports.ask(req, { signal: request.signal }).then(response => {
          if (epoch === this.epoch && !this.disposed && !request.signal.aborted) this.dispatch({ type: 'RESPONSE', response, now: this.ports.now() });
        }).catch(error => {
          if (epoch === this.epoch && !this.disposed && !request.signal.aborted) { this.ports.onError(error); this.dispatch({ type: 'FAIL' }); }
        });
      });
      return;
    }
    const epoch = this.epoch;
    const state = this.state;
    const request = new AbortController(); this.request = request;
    this.capture = this.capture.then(async () => {
      if (epoch !== this.epoch || this.disposed) return;
      const audio = await this.ports.stopCapture();
      if (epoch !== this.epoch || this.disposed) return;
      const w = state.walkthrough;
      const req: AskRequest = { session_id: state.session_id, audio: { format: 'pcm_s16le', channels: 1, ...audio },
        revision: w?.revision ?? null, context: { doc_id: w?.doc_id ?? null, step_id: w?.steps[w.index]?.step_id ?? null } };
      // Don't hold the capture queue while waiting on the relay. Cancel must
      // stop audio even if the relay ignores AbortSignal.
      void this.ports.ask(req, { signal: request.signal }).then(response => {
        if (epoch === this.epoch && !this.disposed && !request.signal.aborted) this.dispatch({ type: 'RESPONSE', response, now: this.ports.now() });
      }).catch(error => {
        if (epoch === this.epoch && !this.disposed && !request.signal.aborted) { this.ports.onError(error); this.dispatch({ type: 'FAIL' }); }
      });
    }).catch(error => {
      this.ports.onError(error);
      if (epoch === this.epoch && !this.disposed) this.dispatch({ type: 'FAIL' });
    });
  }
  async suspend(): Promise<void> {
    this.suspended = true; clearTimeout(this.timer);
    if (this.state.screen === 'LISTENING' || this.state.screen === 'THINKING') this.dispatch({ type: 'DISMISS' });
    await this.ports.persist(this.state);
  }
  async resume(): Promise<void> {
    if (this.disposed) return;
    this.suspended = false;
    if (this.deadline && this.ports.now() >= this.deadline) this.dispatch({ type: 'TIMEOUT' });
    else if (this.deadline) {
      clearTimeout(this.timer);
      this.timer = setTimeout(() => this.dispatch({ type: 'TIMEOUT' }), this.deadline - this.ports.now());
    }
    await this.ports.render(this.state, this.level);
  }
  async dispose(): Promise<void> {
    this.disposed = true; clearTimeout(this.timer); this.epoch += 1; this.request?.abort();
    await this.capture; await this.ports.stopCapture(); await this.ports.persist(this.state);
  }
}
