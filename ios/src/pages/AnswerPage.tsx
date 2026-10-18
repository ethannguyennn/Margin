import { AnswerDetail } from '../components/AnswerDetail';
import { LatencyPanel } from '../components/LatencyPanel';
import { SessionHistory } from '../components/SessionHistory';
import { Walkthrough } from '../components/Walkthrough';
import { QUICK_ASKS } from '../quick-asks';
import { useStore } from '../store';

/** Everything the glance line had to leave out: full text, citations, walkthrough. */
export default function AnswerPage() {
  const { state, askNow, busy, error, clearError, setContext, repeatLast } = useStore();
  const res = state.lastAnswer;
  const history = state.history;

  return (
    <div className="cols">
      <div className="col">
        {error && (
          <section className="card error-card">
            <div className="row between">
              <span>{error.code}</span>
              <button className="btn" onClick={clearError}>
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
                <button key={q.label} className="btn" disabled={busy === 'ask'} onClick={() => void askNow(q.text)}>
                  {q.label}
                </button>
              ))}
            </div>
          </section>
        )}

        {res && (
          <>
            <div className="row wrap">
              <button className="btn" disabled={busy === 'ask'} onClick={() => void repeatLast()}>
                Repeat on lens
              </button>
              <span className="meta">Same session, answered from the relay's memory.</span>
            </div>
            <AnswerDetail key={res.trace_id} res={res} />
          </>
        )}
      </div>

      {(res || history.length > 0) && (
        <div className="col">
          {res?.walkthrough && res.walkthrough.steps.length > 0 && (
            <Walkthrough
              key={`${res.walkthrough.doc_id}-${res.trace_id}`}
              wt={res.walkthrough}
              pinnedStepId={state.context.step_id}
              onUse={(step) =>
                setContext({ doc_id: res.walkthrough?.doc_id ?? state.context.doc_id, step_id: step.step_id })
              }
            />
          )}
          {res && <LatencyPanel res={res} />}
          {history.length > 0 && <SessionHistory history={history} sessionId={state.sessionId} />}
        </div>
      )}
    </div>
  );
}
