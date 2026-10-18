import { loadError } from '../copy';
import { LoadError } from './OfflineBanner';
import { useProcedures, useSteps } from '../hooks/useSops';
import { useStore } from '../store';

/** What the next question is answered against — the phone sets what the lens asks with. */
export function ContextPicker() {
  const { state, setContext, clearContext } = useStore();
  const { procedures, loading, error, retry } = useProcedures();

  const docId = state.context.doc_id;
  const procedure = procedures.find((p) => p.doc_id === docId) ?? null;
  const { steps, loading: stepsLoading } = useSteps(docId, procedure?.revision ?? null);

  return (
    <section className="card">
      <div className="row between">
        <h2 className="section-title">Context</h2>
        {docId && (
          <button className="link" onClick={clearContext}>
            Clear
          </button>
        )}
      </div>

      <label className="field">
        <span>Procedure</span>
        <select
          value={docId ?? ''}
          disabled={loading}
          onChange={(e) => setContext({ doc_id: e.target.value || null, step_id: null })}
        >
          <option value="">{loading ? 'Loading…' : 'No procedure'}</option>
          {procedures.map((p) => (
            <option key={`${p.doc_id}-${p.revision}`} value={p.doc_id}>
              {p.doc_id} · {p.title}
            </option>
          ))}
        </select>
      </label>

      {docId && (
        <label className="field">
          <span>Step</span>
          <select
            value={state.context.step_id ?? ''}
            disabled={stepsLoading}
            onChange={(e) => setContext({ doc_id: docId, step_id: e.target.value || null })}
          >
            <option value="">{stepsLoading ? 'Loading…' : 'Whole procedure'}</option>
            {steps.map((s) => (
              <option key={s.step_id} value={s.step_id}>
                {s.label} — {s.glance}
              </option>
            ))}
          </select>
        </label>
      )}

      <p className="meta">
        {docId
          ? `Questions are answered against ${state.context.step_id ?? `${docId} as a whole`}.`
          : 'Questions are answered against the whole corpus.'}
      </p>
      {error && <LoadError message={loadError(error)} detail={error} onRetry={retry} />}
    </section>
  );
}
