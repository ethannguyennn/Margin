import { stepGraphic } from '../../ui/sop-graphics';
import { SopGraphic } from '../components/SopGraphic';
import { useState } from 'react';
import type { Step } from '../contract';
import { DeviationForm } from '../components/DeviationForm';
import { ChevronIcon } from '../components/Icons';
import { LoadError } from '../components/OfflineBanner';
import { PinButton } from '../components/PinButton';
import { loadError } from '../copy';
import { useProcedures, useSteps } from '../hooks/useSops';
import { useStore } from '../store';

/** Procedures as the relay holds them, and the deviation log the phone can write to. */
export default function SopsPage() {
  const { state, setContext } = useStore();
  const { procedures, loading, error, retry } = useProcedures();
  const [openDoc, setOpenDoc] = useState<string | null>(null);
  const open = procedures.find((p) => p.doc_id === openDoc) ?? null;

  return (
    <div className="stack">
      <section className="card">
        <div className="row between">
          <h2 className="section-title">Procedures</h2>
          {!loading && <span className="meta num">{procedures.length}</span>}
        </div>
        {loading && <SkeletonRows count={3} />}
        {error && <LoadError message={loadError(error)} detail={error} onRetry={retry} />}
        {!loading && !error && procedures.length === 0 && (
          <p className="body">No procedures have been published yet.</p>
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
                    Revision {p.revision} · {p.status}
                  </span>
                </span>
                <ChevronIcon className={`chev${openDoc === p.doc_id ? ' open' : ''}`} />
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
  const { steps, loading, error, retry } = useSteps(docId, revision);

  return (
    <section className="card">
      <div className="row between">
        <h2 className="section-title">{docId} steps</h2>
        <span className="meta">Revision {revision}</span>
      </div>
      {loading && <SkeletonRows count={2} tall />}
      {error && <LoadError message={loadError(error)} detail={error} onRetry={retry} />}
      <ul className="list steps-list">
        {steps.map((s) => (
          <li key={s.step_id}>
            <p className="step-label">{s.label}</p>
            <p className="glance sm">{s.glance}</p>
            <p className="body">{s.body}</p>
            <SopGraphic graphic={stepGraphic(s)} />
            <PinButton pinned={pinnedStepId === s.step_id} onPin={() => onUse(s)} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function SkeletonRows({ count, tall = false }: { count: number; tall?: boolean }) {
  return (
    <div className="list" aria-busy="true" aria-label="Loading">
      {Array.from({ length: count }, (_, i) => (
        <span key={i} className={`skeleton ${tall ? 'sk-block' : 'sk-row'}`} />
      ))}
    </div>
  );
}
