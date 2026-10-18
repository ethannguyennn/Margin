import { useState } from 'react';
import type { Step } from '../contract';
import { DeviationForm } from '../components/DeviationForm';
import { useProcedures, useSteps } from '../hooks/useSops';
import { useStore } from '../store';

/** Procedures as the relay holds them, and the deviation log the phone can write to. */
export default function SopsPage() {
  const { state, setContext } = useStore();
  const { procedures, loading, error } = useProcedures();
  const [openDoc, setOpenDoc] = useState<string | null>(null);
  const open = procedures.find((p) => p.doc_id === openDoc) ?? null;

  return (
    <div className="stack">
      <section className="card">
        <div className="row between">
          <h2 className="section-title">Procedures</h2>
          <span className="meta">{procedures.length} loaded</span>
        </div>
        {loading && <p className="meta">Loading…</p>}
        {error && <p className="error-line">{error}</p>}
        {!loading && !error && procedures.length === 0 && (
          <p className="body">The relay listed no procedures. Is the database reachable?</p>
        )}
        <ul className="list">
          {procedures.map((p) => (
            <li key={`${p.doc_id}-${p.revision}`}>
              <button
                className={`row-item${openDoc === p.doc_id ? ' on' : ''}`}
                onClick={() => setOpenDoc(openDoc === p.doc_id ? null : p.doc_id)}
              >
                <span className="row-item-main">
                  <span className="row-item-title">
                    {p.doc_id} · {p.title}
                  </span>
                  <span className="meta">
                    rev {p.revision} · {p.status}
                  </span>
                </span>
                <span className="chev">{openDoc === p.doc_id ? '−' : '+'}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      {open && (
        <StepList
          key={`${open.doc_id}-${open.revision}`}
          docId={open.doc_id}
          revision={open.revision}
          pinnedStepId={state.context.step_id}
          onUse={(step) => setContext({ doc_id: open.doc_id, step_id: step.step_id })}
        />
      )}

      <DeviationForm />
    </div>
  );
}

function StepList({
  docId,
  revision,
  pinnedStepId,
  onUse,
}: {
  docId: string;
  revision: string;
  pinnedStepId: string | null;
  onUse: (step: Step) => void;
}) {
  const { steps, loading, error } = useSteps(docId, revision);

  return (
    <section className="card">
      <div className="row between">
        <h2 className="section-title">{docId} steps</h2>
        <span className="meta">rev {revision}</span>
      </div>
      {loading && <p className="meta">Loading…</p>}
      {error && <p className="error-line">{error}</p>}
      <ul className="list steps-list">
        {steps.map((s) => (
          <li key={s.step_id}>
            <p className="step-label">{s.label}</p>
            <p className="glance sm">{s.glance}</p>
            <p className="body">{s.body}</p>
            <button className="btn" onClick={() => onUse(s)}>
              {pinnedStepId === s.step_id ? 'Pinned as lens context ✓' : 'Pin as lens context'}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
