import { AnswerDetail } from '../components/AnswerDetail';
import { outcomeTone, Pill } from '../components/Pills';
import { QUICK_ASKS } from '../quick-asks';
import { useStore } from '../store';

/** Everything the glance line had to leave out: full text, citations, walkthrough. */
export default function AnswerPage() {
  const { state, askNow, busy, error, clearError, setContext, repeatLast } = useStore();
  const res = state.lastAnswer;

  return (
    <div className="stack">
      {error && (
        <section className="card error-card">
          <div className="row between">
            <strong>{error.code}</strong>
            <button className="link" onClick={clearError}>
              Dismiss
            </button>
          </div>
          <p className="meta">{error.message}</p>
        </section>
      )}

      {!res && (
        <section className="card">
          <h2 className="section-title">No answer yet</h2>
          <p className="body">
            The lens shows one glance line. The phone keeps the whole answer: full text, citations,
            the walkthrough and where the time went.
          </p>
          <p className="meta">Ask from the Lens tab, or try one of these:</p>
          <div className="row wrap">
            {QUICK_ASKS.map((q) => (
              <button key={q.label} className="chip" disabled={busy === 'ask'} onClick={() => void askNow(q.text)}>
                {q.label}
              </button>
            ))}
          </div>
        </section>
      )}

      {res && (
        <>
          <div className="row wrap">
            <button className="ghost" disabled={busy === 'ask'} onClick={() => void repeatLast()}>
              Repeat on lens
            </button>
            <span className="meta">Same session, answered from the relay's memory.</span>
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
                  <Pill tone={outcomeTone(x.outcome)}>{x.outcome}</Pill>
                  <span className="meta">{new Date(x.at).toLocaleTimeString()}</span>
                </div>
                <p className="meta">{x.question}</p>
                <p className="history-glance">{x.glance}</p>
              </li>
            ))}
          </ul>
          <p className="meta mono">session {state.sessionId.slice(0, 8)}</p>
        </section>
      )}
    </div>
  );
}
