import { useEffect, useState } from 'react';
import type { Procedure, Step } from '../contract';
import { asRelayError, listProcedures, listSteps } from '../relay';
import { useStore } from '../store';

/** /v1/procedures — what the relay holds, one row per revision. */
export function useProcedures() {
  const { sessionId } = useStore();
  const [procedures, setProcedures] = useState<Procedure[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    listProcedures(sessionId)
      .then((rows) => {
        if (!alive) return;
        setProcedures(rows);
        setError(null);
      })
      .catch((e) => {
        if (alive) setError(asRelayError(e).message);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [sessionId, attempt]);

  return { procedures, loading, error, retry: () => setAttempt((n) => n + 1) };
}

/** /v1/procedures/{doc_id}/steps — the walkthrough the lens pages through. */
export function useSteps(docId: string | null, revision: string | null) {
  const { sessionId } = useStore();
  const [steps, setSteps] = useState<Step[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!docId) {
      setSteps([]);
      setError(null);
      setLoading(false);
      return;
    }
    let alive = true;
    setLoading(true);
    listSteps(sessionId, docId, revision)
      .then((rows) => {
        if (!alive) return;
        setSteps(rows);
        setError(null);
      })
      .catch((e) => {
        if (alive) setError(asRelayError(e).message);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [docId, revision, sessionId, attempt]);

  return { steps, loading, error, retry: () => setAttempt((n) => n + 1) };
}
