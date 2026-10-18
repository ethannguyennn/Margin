import { useEffect, useState } from 'react';
import type { Procedure, Step } from '../contract';
import { asRelayError, listProcedures, listSteps } from '../relay';
import { useStore } from '../store';

/** /v1/procedures — what the relay holds, one row per revision. */
export function useProcedures() {
  const { state } = useStore();
  const [procedures, setProcedures] = useState<Procedure[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    listProcedures(state.sessionId)
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
  }, [state.sessionId]);

  return { procedures, loading, error };
}

/** /v1/procedures/{doc_id}/steps — the walkthrough the lens pages through. */
export function useSteps(docId: string | null, revision: string | null) {
  const { state } = useStore();
  const [steps, setSteps] = useState<Step[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!docId) {
      setSteps([]);
      setError(null);
      setLoading(false);
      return;
    }
    let alive = true;
    setLoading(true);
    listSteps(state.sessionId, docId, revision)
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
  }, [docId, revision, state.sessionId]);

  return { steps, loading, error };
}
