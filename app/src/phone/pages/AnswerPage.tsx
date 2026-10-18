import { Link } from 'react-router-dom';
import { AnswerDetail } from '../components/AnswerDetail';
import { OutcomePill } from '../components/Pills';
import { clockTime, errorTitle, shortId } from '../copy';
import { useStore } from '../store';

/** Everything the glance line had to leave out: full text, citations, walkthrough. */
export default function AnswerPage() {
  const { state, sessionId, busy, error, clearError, setContext, repeatLast } = useStore();
  const res = state.lastAnswer;

  return (
    <div className="stack">
      {error && (
        <section className="card error-card">
          <div className="row between">
            <strong>{errorTitle(error.code)}</strong>
            <button className="link" onClick={clearError}>
              Dismiss
            </button>
          </div>
          <p className="meta" title={error.code}>
            {error.message}
          </p>
        </section>
      )}

      {!res && (
        <section className="card">
          <h2 className="section-title">No answer yet</h2>
          <p className="body">Ask on your glasses or here. The full answer and its sources show up on this page.</p>
          <div className="row wrap">
            <Link className="ghost with-icon" to="/lens">
              Ask a question
            </Link>
            <Link className="ghost with-icon" to="/sops">
              Browse procedures
            </Link>
          </div>
        </section>
      )}

      {res && (
        <>
          <div className="row wrap">
            <button className="ghost" disabled={busy === 'ask'} onClick={() => void repeatLast()}>
              Repeat on lens
            </button>
            <span className="meta">Shows this answer on your glasses again.</span>
          </div>
          <AnswerDetail
            key={res.trace_id}
            res={res}
            pinnedStepId={state.context.step_id}
            onUseStep={(step) =>
              setContext({ doc_id: res.walkthrough?.doc_id ?? state.context.doc_id, step_id: step.step_id })
            }
          />
        </>
      )}

      {state.history.length > 0 && (
        <section className="card">
          <h2 className="section-title">This session</h2>
          <ul className="list history">
            {state.history.map((x, i) => (
              <li key={`${x.trace_id}-${i}`}>
                <div className="row between">
                  <OutcomePill outcome={x.outcome} />
                  <span className="meta num">{clockTime(x.at)}</span>
                </div>
                <p className="meta">{x.question}</p>
                <p className="history-glance">{x.glance}</p>
              </li>
            ))}
          </ul>
          <p className="meta num">Session {shortId(sessionId)}</p>
        </section>
      )}
    </div>
  );
}
