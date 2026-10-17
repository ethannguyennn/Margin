import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ContextPicker } from '../components/ContextPicker';
import { OutcomePill } from '../components/Pills';
import { QUICK_ASKS } from '../quick-asks';
import { relayOrigin } from '../relay';
import { useStore } from '../store';

/**
 * The phone as the second display for the lens session: it holds the session, sets
 * the context the next question is answered against, and can ask in words.
 */
export default function LensPage() {
  const {
    state,
    health,
    healthChecked,
    busy,
    askNow,
    repeatLast,
    setListening,
    setMicSource,
    startNewSession,
  } = useStore();
  const [question, setQuestion] = useState('');
  const res = state.lastAnswer;

  const submit = async () => {
    const answer = await askNow(question);
    if (answer) setQuestion('');
  };

  return (
    <div className="stack">
      <section className="card">
        <div className="row between">
          <h2 className="section-title">Session</h2>
          <button className="link" onClick={startNewSession}>
            New session
          </button>
        </div>
        <p className="meta mono">session {state.sessionId}</p>

        <div className="row between mt">
          <span className="label">Listening</span>
          <button
            type="button"
            role="switch"
            aria-checked={state.listening}
            aria-label="Listening"
            className={`switch${state.listening ? ' on' : ''}`}
            onClick={() => setListening(!state.listening)}
          >
            <span />
          </button>
        </div>

        <div className="row between mt">
          <span className="label">Mic source</span>
          <div className="segmented">
            {(['glasses', 'phone'] as const).map((source) => (
              <button
                key={source}
                className={state.micSource === source ? 'on' : ''}
                onClick={() => setMicSource(source)}
              >
                {source}
              </button>
            ))}
          </div>
        </div>

        <p className="meta mt">
          {relayOrigin || 'Relay origin not set'} ·{' '}
          {!healthChecked
            ? 'checking…'
            : health
              ? `v${health.version}, db ${health.db}${health.mock ? ', mock' : ''}`
              : 'unreachable'}
        </p>
        <p className="meta">
          The phone asks under this session. The glasses app starts its own on launch, and nothing is
          pushed to it yet — this panel drives the relay, it does not read the lens.
        </p>
      </section>

      <ContextPicker />

      <section className="card">
        <h2 className="section-title">Ask for the lens</h2>
        <textarea
          className="input"
          rows={2}
          placeholder="Type what you would say out loud…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <div className="row wrap">
          <button className="primary" disabled={busy === 'ask' || !question.trim()} onClick={() => void submit()}>
            {busy === 'ask' ? 'Asking…' : 'Ask'}
          </button>
          <button className="ghost" disabled={busy === 'ask'} onClick={() => void repeatLast()}>
            Repeat last
          </button>
        </div>
        <div className="row wrap">
          {QUICK_ASKS.slice(0, 3).map((q) => (
            <button
              key={q.label}
              className="chip"
              disabled={busy === 'ask'}
              onClick={() => void askNow(q.text)}
            >
              {q.label}
            </button>
          ))}
        </div>
      </section>

      {res && (
        <section className="card">
          <div className="row between">
            <h2 className="section-title">What the lens shows</h2>
            <Link className="link" to="/">
              Full answer
            </Link>
          </div>
          <div className="row wrap">
            <OutcomePill outcome={res.outcome} />
          </div>
          <p className="glance">{res.glance}</p>
          {res.source && <p className="meta">Source · {res.source}</p>}
          {res.walkthrough && (
            <p className="meta">
              {res.walkthrough.total} steps · open Answer to walk them
            </p>
          )}
        </section>
      )}
    </div>
  );
}
