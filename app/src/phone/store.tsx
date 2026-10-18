// The phone screen's state. Two modes:
// - Linked (inside the Even app, glasses connected): the lens controller owns the
//   session. Typed questions go through it (lens-link.ts), so the glasses show the
//   answer too, and every answer the lens receives, spoken or typed, lands here.
// - Standalone (plain browser preview, no Even bridge): asks go straight to the relay
//   under a phone-only session, exactly like the old ios/ companion.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from 'react';
import type { AskResponse, DeviationResult, Health } from './contract';
import * as relay from './relay';
import { lensLink, type LensExchange, type LensSnapshot } from '../lens-link';
import { ASK_TIMEOUT_MS, setMicSource as persistMicSource } from '../settings';
import {
  HISTORY_MAX,
  NO_CONTEXT,
  loadSession,
  newSession,
  saveSession,
  uuid,
  type Exchange,
  type MicSource,
  type SessionState,
  type StepContext,
} from './session';

export interface StoreError {
  code: string;
  message: string;
}

export type Busy = 'ask' | 'deviation' | null;

interface StoreValue {
  state: SessionState;
  lens: LensSnapshot;
  /** The session the relay sees: the lens's when linked, the phone's otherwise. */
  sessionId: string;
  health: Health | null;
  healthChecked: boolean;
  busy: Busy;
  error: StoreError | null;
  clearError: () => void;
  setContext: (ctx: StepContext) => void;
  clearContext: () => void;
  canPushToTalk: boolean;
  togglePushToTalk: () => void;
  setMicSource: (source: MicSource) => void;
  askNow: (question: string) => Promise<AskResponse | null>;
  repeatLast: () => Promise<AskResponse | null>;
  submitDeviation: (text: string) => Promise<DeviationResult | null>;
  startNewSession: () => void;
}

const StoreContext = createContext<StoreValue | null>(null);

// The lens client times out at ASK_TIMEOUT_MS and retries once; leave room for both.
const LINKED_ASK_WAIT_MS = ASK_TIMEOUT_MS * 2 + 4000;

function exchangeOf(question: string, res: AskResponse): Exchange {
  return {
    at: Date.now(),
    question,
    intent: res.intent,
    outcome: res.outcome,
    glance: res.glance,
    trace_id: res.trace_id,
  };
}

function errorOf(res: AskResponse): StoreError | null {
  return res.outcome === 'error' ? { code: res.error?.code ?? 'error', message: res.error?.message ?? 'The relay could not answer.' } : null;
}

export function StoreProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>(loadSession);
  const lens = useSyncExternalStore(lensLink.subscribe, lensLink.getSnapshot);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthChecked, setHealthChecked] = useState(false);
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<StoreError | null>(null);

  const linked = lens.connected && !!lens.sessionId;
  const sessionId = linked ? (lens.sessionId as string) : state.sessionId;

  // Read inside callbacks by ref: a poll or a stale closure must never ask as an old session.
  const sessionRef = useRef(sessionId);
  sessionRef.current = sessionId;
  const contextRef = useRef(state.context);
  contextRef.current = state.context;
  const linkedRef = useRef(linked);
  linkedRef.current = linked;

  useEffect(() => saveSession(state), [state]);

  // Every answer the lens receives (spoken on the glasses or typed here).
  const pending = useRef<((res: AskResponse | null) => void) | null>(null);
  useEffect(() => {
    const record = ({ response, question }: LensExchange) => {
      setState((s) => ({
        ...s,
        lastAnswer: response,
        history: [exchangeOf(question ?? response.transcript ?? '', response), ...s.history].slice(0, HISTORY_MAX),
      }));
      setError(errorOf(response));
      pending.current?.(response);
    };
    const offExchange = lensLink.onExchange(record);
    // A typed ask that leaves THINKING without an answer was cancelled on the glasses
    // (double press) or failed: stop waiting for it.
    let previous = lensLink.getSnapshot().screen;
    const offScreen = lensLink.subscribe(() => {
      const screen = lensLink.getSnapshot().screen;
      if (previous === 'THINKING' && screen !== 'THINKING') queueMicrotask(() => pending.current?.(null));
      previous = screen;
    });
    return () => { offExchange(); offScreen(); };
  }, []);

  const checkHealth = useCallback(async () => {
    try {
      setHealth(await relay.health(sessionRef.current));
    } catch {
      setHealth(null);
    } finally {
      setHealthChecked(true);
    }
  }, []);

  useEffect(() => {
    void checkHealth();
    const timer = setInterval(() => void checkHealth(), 20000);
    return () => clearInterval(timer);
  }, [checkHealth]);

  const askThroughLens = useCallback((text: string): Promise<AskResponse | null> => {
    return new Promise((resolve) => {
      let settled = false;
      const timer = setTimeout(() => finish(null), LINKED_ASK_WAIT_MS);
      function finish(res: AskResponse | null) {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (pending.current === finish) pending.current = null;
        resolve(res);
      }
      pending.current = finish;
      if (!lensLink.askText(text, contextRef.current)) {
        const screen = lensLink.getSnapshot().screen;
        setError(screen === 'PRIVACY'
          ? { code: 'privacy', message: 'Press once on the glasses to acknowledge the privacy notice first.' }
          : { code: 'busy', message: 'The lens is already answering a question.' });
        finish(null);
      }
    });
  }, []);

  const runAsk = useCallback(
    async (question: string): Promise<AskResponse | null> => {
      const text = question.trim();
      if (!text) return null;
      setBusy('ask');
      setError(null);
      try {
        if (linkedRef.current) return await askThroughLens(text);
        const res = await relay.ask(sessionRef.current, text, contextRef.current);
        setState((s) => ({
          ...s,
          lastAnswer: res,
          history: [exchangeOf(text, res), ...s.history].slice(0, HISTORY_MAX),
        }));
        return res;
      } catch (e) {
        setError(relay.asRelayError(e));
        return null;
      } finally {
        setBusy(null);
      }
    },
    [askThroughLens],
  );

  // The relay answers "repeat" from its own session memory, so this is the same
  // session's last answer with no pipeline run.
  const repeatLast = useCallback(() => runAsk('repeat'), [runAsk]);

  const submitDeviation = useCallback(async (text: string): Promise<DeviationResult | null> => {
    const body = text.trim();
    if (!body) return null;
    setBusy('deviation');
    setError(null);
    try {
      return await relay.logDeviation(sessionRef.current, body, contextRef.current);
    } catch (e) {
      setError(relay.asRelayError(e));
      return null;
    } finally {
      setBusy(null);
    }
  }, []);

  const canPushToTalk = linked && lensLink.canTogglePushToTalk();

  const value = useMemo<StoreValue>(
    () => ({
      state: { ...state, listening: lens.screen === 'LISTENING' },
      lens,
      sessionId,
      health,
      healthChecked,
      busy,
      error,
      clearError: () => setError(null),
      setContext: (ctx) => setState((s) => ({ ...s, context: ctx })),
      clearContext: () => setState((s) => ({ ...s, context: NO_CONTEXT })),
      canPushToTalk,
      togglePushToTalk: () => lensLink.togglePushToTalk(),
      setMicSource: (micSource) => {
        persistMicSource(micSource); // read by audio/capture.ts on the next press
        setState((s) => ({ ...s, micSource }));
      },
      askNow: runAsk,
      repeatLast,
      submitDeviation,
      startNewSession: () => {
        setError(null);
        // Linked: the lens owns the session, so only the phone's history is cleared.
        setState((s) => (linkedRef.current ? { ...s, lastAnswer: null, history: [] } : newSession(uuid())));
      },
    }),
    [state, lens, sessionId, health, healthChecked, busy, error, canPushToTalk, runAsk, repeatLast, submitDeviation],
  );

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore(): StoreValue {
  const value = useContext(StoreContext);
  if (!value) throw new Error('useStore must be used inside <StoreProvider>');
  return value;
}
