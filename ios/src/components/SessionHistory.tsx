import type { Exchange } from '../session';
import { outcomeTone, Pill } from './Pills';

/** Every ask of this session, newest first — the record the phone keeps. */
export function SessionHistory({ history, sessionId }: { history: Exchange[]; sessionId: string }) {
  return (
    <section className="card">
      <h2 className="section-title">This session</h2>
      <div className="hist">
        {history.map((x, i) => (
          <div className="hist-row" key={`${x.trace_id}-${i}`}>
            <div className="row between">
              <Pill tone={outcomeTone(x.outcome)}>{x.outcome}</Pill>
              <span className="meta">{new Date(x.at).toLocaleTimeString()}</span>
            </div>
            <p className="meta">{x.question}</p>
            <p className="body">{x.glance}</p>
          </div>
        ))}
      </div>
      <p className="meta mono">session {sessionId.slice(0, 8)}</p>
    </section>
  );
}
