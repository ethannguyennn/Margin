// The phone's half of the pair: one session, one SOP context, one in-flight action.
// The lens app keeps its own session; this store is what the phone asks under.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import type { AskResponse, DeviationResult, Health } from './contract';
import * as relay from './relay';
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
  health: Health | null;
  healthChecked: boolean;
  busy: Busy;
  error: StoreError | null;
  clearError: () => void;
  setContext: (ctx: StepContext) => void;
  clearContext: () => void;
  setListening: (listening: boolean) => void;
  setMicSource: (source: MicSource) => void;
  askNow: (question: string) => Promise<AskResponse | null>;
  repeatLast: () => Promise<AskResponse | null>;
  submitDeviation: (text: string) => Promise<DeviationResult | null>;
  startNewSession: () => void;
}

const StoreContext = createContext<StoreValue | null>(null);

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

export function StoreProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>(loadSession);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthChecked, setHealthChecked] = useState(false);
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<StoreError | null>(null);

  // Read inside callbacks by ref: a poll or a stale closure must never ask as an old session.
  const sessionRef = useRef(state.sessionId);
  sessionRef.current = state.sessionId;
  const contextRef = useRef(state.context);
  contextRef.current = state.context;

  useEffect(() => saveSession(state), [state]);

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

  const runAsk = useCallback(
    async (question: string): Promise<AskResponse | null> => {
      const text = question.trim();
      if (!text) return null;
      setBusy('ask');
      setError(null);
      try {
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
    [],
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

  const value = useMemo<StoreValue>(
    () => ({
      state,
      health,
      healthChecked,
      busy,
      error,
      clearError: () => setError(null),
      setContext: (ctx) => setState((s) => ({ ...s, context: ctx })),
      clearContext: () => setState((s) => ({ ...s, context: NO_CONTEXT })),
      setListening: (listening) => setState((s) => ({ ...s, listening })),
      setMicSource: (micSource) => setState((s) => ({ ...s, micSource })),
      askNow: runAsk,
      repeatLast,
      submitDeviation,
      startNewSession: () => {
        setError(null);
        setState(newSession(uuid()));
      },
    }),
    [state, health, healthChecked, busy, error, runAsk, repeatLast, submitDeviation],
  );

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore(): StoreValue {
  const value = useContext(StoreContext);
  if (!value) throw new Error('useStore must be used inside <StoreProvider>');
  return value;
}
