import { useState } from 'react';
import type { Step, Walkthrough as WalkthroughShape } from '../contract';
import { stepGraphic } from '../../ui/sop-graphics';
import { SopGraphic } from './SopGraphic';

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
      <p className="wt-title">{wt.title}</p>

      <div className="row wrap steps">
        {wt.steps.map((s, i) => (
          <button
            key={s.step_id}
            className={`chip${i === index ? ' on' : ''}`}
            onClick={() => setIndex(i)}
            aria-current={i === index}
          >
            {s.label}
          </button>
        ))}
      </div>

      <SopGraphic graphic={stepGraphic(step)} />
      <p className="glance sm">{step.glance}</p>
      <p className="body">{step.body}</p>

      <div className="row between">
        <button className="ghost" onClick={() => setIndex(Math.max(0, index - 1))} disabled={index === 0}>
          Previous
        </button>
        <span className="meta">
          {index + 1} / {wt.steps.length}
        </span>
        <button className="ghost" onClick={() => setIndex(Math.min(last, index + 1))} disabled={index === last}>
          Next
        </button>
      </div>

      <button className="primary wide" onClick={() => onUse(step)}>
        {pinnedStepId === step.step_id ? 'Pinned as lens context ✓' : 'Pin as lens context'}
      </button>
    </section>
  );
}
