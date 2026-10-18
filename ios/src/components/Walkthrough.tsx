import { useState } from 'react';
import type { Step, Walkthrough as WalkthroughShape } from '../contract';

/** The lens pages through these one at a time; the phone can see them all at once. */
export function Walkthrough({
  wt,
  pinnedStepId,
  onUse,
}: {
  wt: WalkthroughShape;
  pinnedStepId: string | null;
  onUse: (step: Step) => void;
}) {
  const last = wt.steps.length - 1;
  const [index, setIndex] = useState(Math.min(Math.max(wt.index ?? 0, 0), last));
  const step = wt.steps[index];
  if (!step) return null;

  return (
    <section className="card">
      <div className="row between">
        <h2 className="section-title">Walkthrough</h2>
        <span className="meta">
          {wt.doc_id} rev {wt.revision}
        </span>
      </div>
      <p className="lbl">{wt.title}</p>

      <ol className="steps">
        {wt.steps.map((s, i) => (
          <li key={s.step_id}>
            <span className="n">{i + 1}</span>
            <span>{s.glance}</span>
          </li>
        ))}
      </ol>

      <div className="row wrap">
        {wt.steps.map((s, i) => (
          <button
            key={s.step_id}
            className={`btn${i === index ? ' on' : ''}`}
            onClick={() => setIndex(i)}
            aria-current={i === index}
          >
            {i + 1}
          </button>
        ))}
      </div>

      <p className="glance sm">{step.glance}</p>
      <p className="body">{step.body}</p>

      <div className="row between">
        <button className="btn" onClick={() => setIndex(Math.max(0, index - 1))} disabled={index === 0}>
          Previous
        </button>
        <span className="meta">
          {index + 1} / {wt.steps.length}
        </span>
        <button className="btn" onClick={() => setIndex(Math.min(last, index + 1))} disabled={index === last}>
          Next
        </button>
      </div>

      <button className="btn pri" onClick={() => onUse(step)}>
        {pinnedStepId === step.step_id ? 'Pinned as lens context ✓' : 'Pin as lens context'}
      </button>
    </section>
  );
}
