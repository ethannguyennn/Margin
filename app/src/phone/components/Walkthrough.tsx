import { stepGraphic } from '../../ui/sop-graphics';
import { SopGraphic } from './SopGraphic';
import { useRef, useState } from 'react';
import type { Step, Walkthrough as WalkthroughShape } from '../contract';
import { ChevronIcon } from './Icons';
import { PinButton } from './PinButton';

/**
 * The lens pages through these one at a time; the phone shows where you are in
 * the whole procedure. Big Previous / Next targets (gloved hands), a segmented
 * progress bar that jumps to any step, and swipe left / right on the step.
 */
export function Walkthrough({
  wt,
  pinnedStepId,
  onUse,
}: {
  wt: WalkthroughShape;
  pinnedStepId: string | null;
  onUse: (step: Step) => void;
}) {
  // v3: a spoken walkthrough is scoped to the steps asked for; the whole procedure is one tap away.
  const scope = wt.scope && wt.scope.start >= 0 && wt.scope.start < wt.scope.end && wt.scope.end <= wt.steps.length ? wt.scope : null;
  const [whole, setWhole] = useState(!scope);
  const first = whole || !scope ? 0 : scope.start;
  const last = (whole || !scope ? wt.steps.length : scope.end) - 1;
  const [index, setIndex] = useState(Math.min(Math.max(wt.index ?? 0, first), last));
  const [direction, setDirection] = useState<'next' | 'back'>('next');
  const touchX = useRef<number | null>(null);
  const step = wt.steps[index];
  if (!step) return null;

  const go = (to: number) => {
    const target = Math.min(Math.max(to, first), last);
    if (target === index) return;
    setDirection(target > index ? 'next' : 'back');
    setIndex(target);
  };

  return (
    <section className="card">
      <div className="row between">
        <h2 className="section-title">Walkthrough</h2>
        <span className="meta">
          {wt.doc_id} · Revision {wt.revision}
        </span>
      </div>
      <p className="wt-title">{wt.title}</p>
      {scope && (
        <button className="link" onClick={() => { setWhole(!whole); if (whole) setIndex(Math.min(Math.max(index, scope.start), scope.end - 1)); }}>
          {whole ? 'Show only the steps asked for' : `Show whole procedure (${wt.steps.length} steps)`}
        </button>
      )}

      <div className="wt-progress">
        <div className="row between">
          <span className="wt-count num">
            Step {index - first + 1} <span className="wt-of">of {last - first + 1}</span>
          </span>
          <span className="meta">{step.label}</span>
        </div>
        <div className="wt-track" role="group" aria-label="Steps">
          {wt.steps.map((s, i) => i < first || i > last ? null : (
            <button
              key={s.step_id}
              className={`wt-seg${i < index ? ' done' : ''}${i === index ? ' current' : ''}`}
              aria-label={`Step ${i - first + 1}: ${s.label}`}
              aria-current={i === index ? 'step' : undefined}
              onClick={() => go(i)}
            >
              <span />
            </button>
          ))}
        </div>
      </div>

      <div
        key={index}
        className={`wt-step wt-${direction}`}
        onTouchStart={(e) => {
          touchX.current = e.touches[0]?.clientX ?? null;
        }}
        onTouchEnd={(e) => {
          const start = touchX.current;
          const end = e.changedTouches[0]?.clientX;
          touchX.current = null;
          if (start == null || end == null || Math.abs(end - start) < 50) return;
          go(end < start ? index + 1 : index - 1);
        }}
      >
        <p className="glance">{step.glance}</p>
        {step.warning && (
          <p className="wt-flag wt-warning">
            <strong>Warning</strong>
            {step.warning}
          </p>
        )}
        <p className="body">{step.body}</p>
        <SopGraphic graphic={stepGraphic(step)} />
        {step.checkpoint && (
          <p className="wt-flag">
            <strong>Checkpoint</strong>
            {step.checkpoint}
          </p>
        )}
      </div>

      <div className="wt-nav">
        <button className="ghost with-icon" onClick={() => go(index - 1)} disabled={index === first}>
          <ChevronIcon className="flip" />
          Previous
        </button>
        <button className="primary with-icon" onClick={() => go(index + 1)} disabled={index === last}>
          Next
          <ChevronIcon />
        </button>
      </div>

      <PinButton pinned={pinnedStepId === step.step_id} onPin={() => onUse(step)} />
    </section>
  );
}
