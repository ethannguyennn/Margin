import { GlassesSimulator } from '../components/GlassesSimulator';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ContextPicker } from '../components/ContextPicker';
import { WorkspaceCard } from '../components/WorkspaceCard';
import { ChevronIcon } from '../components/Icons';
import { OutcomePill } from '../components/Pills';
import { glassesStatus, shortId } from '../copy';
import { relayOrigin } from '../relay';
import { useStore } from '../store';
import { toast } from '../toast';

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
  const glasses = glassesStatus(lens.connected, lens.status);
  const server = !healthChecked ? null : health?.ok ? (health.mock ? 'Demo data' : 'Connected') : 'Offline';

  const submit = async () => {
    const answer = await askNow(question);
    if (answer) setQuestion('');
  };

  const resetSession = () => {
    startNewSession();
    toast(lens.connected ? 'History cleared' : 'New session started');
  };

  return (
    <div className="stack">
      <WorkspaceCard />

      <GlassesSimulator />

      <section className="group">
        <h2 className="group-title">Glasses</h2>
        <div className="group-body">
          <div className="group-row">
            <span className="label">Status</span>
            <span className="value" title={lens.status}>
              {glasses.label}
            </span>
          </div>
          <div className="group-row">
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
          <div className="group-row">
            <span className="label">Microphone</span>
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
        </div>
        {glasses.hint && <p className="group-note">{glasses.hint}</p>}
      </section>

      {lens.connected && <section className="card">
        <h2 className="section-title">Ask a question</h2>
        <textarea
          className="input"
          rows={2}
          placeholder="Type what you would say out loud…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <div className="row wrap">
          <button
            className="primary"
            aria-busy={busy === 'ask'}
            disabled={busy === 'ask' || !question.trim()}
            onClick={() => void submit()}
          >
            {busy === 'ask' ? 'Asking…' : 'Ask'}
          </button>
          <button className="ghost" disabled={busy === 'ask'} onClick={() => void repeatLast()}>
            Repeat last
          </button>
        </div>
        <p className="meta">
          {lens.connected
            ? 'Answers also appear on your glasses.'
            : 'Glasses not connected: answers appear here only.'}
        </p>
      </section>}

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
          {res.walkthrough && <p className="meta">{res.walkthrough.total} steps · open Answer to walk through them</p>}
        </section>
      )}

      <ContextPicker />

      <section className="group">
        <h2 className="group-title">Connection</h2>
        <div className="group-body">
          <div className="group-row">
            <span className="label">Server</span>
            {server ? <span className="value">{server}</span> : <span className="skeleton sk-value" aria-label="Checking" />}
          </div>
          <div className="group-row">
            <span className="label">Session</span>
            <span className="value num">{shortId(sessionId)}</span>
          </div>
          <button className="group-row group-action" onClick={resetSession}>
            {lens.connected ? 'Clear history' : 'Start new session'}
          </button>
        </div>

        <details className="disclosure">
          <summary>
            Technical details
            <ChevronIcon size={14} className="disclosure-chev" />
          </summary>
          <dl className="details-list">
            <dt>Server address</dt>
            <dd>{relayOrigin || 'Not configured'}</dd>
            <dt>Server version</dt>
            <dd>{health ? `v${health.version} · database ${health.db}${health.mock ? ' · mock' : ''}` : 'Unreachable'}</dd>
            <dt>Session ID</dt>
            <dd>{sessionId}</dd>
            <dt>Glasses link</dt>
            <dd>{lens.status}</dd>
          </dl>
        </details>
      </section>
    </div>
  );
}
