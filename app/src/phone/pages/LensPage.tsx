import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ContextPicker } from '../components/ContextPicker';
import { OutcomePill } from '../components/Pills';
import { QUICK_ASKS } from '../quick-asks';
import { relayOrigin } from '../relay';
import { useStore } from '../store';

/**
 * The phone side of the lens session. Inside the Even app it drives the glasses:
 * push-to-talk, mic source, typed questions (answered on the lens too), and a live
 * mirror of what the lens displays. In a plain browser it asks the relay directly.
 */
export default function LensPage() {
  const {
    state,
    lens,
    sessionId,
    health,
    healthChecked,
    busy,
    askNow,
    repeatLast,
    canPushToTalk,
    togglePushToTalk,
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
            {lens.connected ? 'Clear history' : 'New session'}
          </button>
        </div>
        <p className="meta mono">session {sessionId}</p>

        <div className="row between mt">
          <span className="label">Glasses</span>
          <span className="meta">{lens.connected ? `connected · ${lens.status}` : lens.status}</span>
        </div>

        <div className="row between mt">
          <span className="label">Push to talk</span>
          <button
            type="button"
            role="switch"
            aria-checked={state.listening}
            aria-label="Push to talk"
            disabled={!canPushToTalk}
            className={`switch${state.listening ? ' on' : ''}`}
            onClick={togglePushToTalk}
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
          {lens.connected
            ? 'Questions typed here are answered on the glasses too, under the lens session.'
            : 'No glasses connected (browser preview): questions go straight to the relay and nothing is shown on a lens.'}
        </p>
      </section>

      <ContextPicker />

      <section className="card">
        <h2 className="section-title">{lens.connected ? 'Ask on the lens' : 'Ask the relay'}</h2>
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

      {lens.connected && lens.lensText && (
        <section className="card">
          <h2 className="section-title">On the lens now</h2>
          <pre className="glance mono">{lens.lensText}</pre>
        </section>
      )}

      {res && (
        <section className="card">
          <div className="row between">
            <h2 className="section-title">Last answer</h2>
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
