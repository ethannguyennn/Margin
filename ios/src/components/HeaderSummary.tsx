import { useLocation } from 'react-router-dom';
import { useStore } from '../store';
import { OutcomePill, Pill, VerifiedPill } from './Pills';

/** The bar keeps the lens's one line in view while the phone reads the rest. */
export function HeaderSummary() {
  const { pathname } = useLocation();
  const { state } = useStore();
  const res = state.lastAnswer;
  if (pathname !== '/' || !res) return null;

  return (
    <>
      <p className="glance">{res.glance || '—'}</p>
      <div className="chips">
        <OutcomePill outcome={res.outcome} />
        <Pill tone="dim">{res.intent}</Pill>
        {res.outcome === 'answered' && <VerifiedPill verified={res.verified} />}
        {res.source && <span className="lbl">Source · {res.source}</span>}
      </div>
    </>
  );
}
