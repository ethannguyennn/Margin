import { useState } from 'react';
import type { DeviationResult } from '../contract';
import { errorTitle } from '../copy';
import { useStore } from '../store';
import { toast } from '../toast';
import { Pill } from './Pills';

/** POST /v1/deviation — the record is the compliance artifact, the alert is a bonus. */
export function DeviationForm() {
  const { state, submitDeviation, busy, error } = useStore();
  const [text, setText] = useState('');
  const [result, setResult] = useState<DeviationResult | null>(null);
  const ctx = state.context;

  const submit = async () => {
    const res = await submitDeviation(text);
    if (res) {
      setResult(res);
      setText('');
      toast('Deviation logged');
    }
  };

  return (
    <section className="card">
      <h2 className="section-title">Log a deviation</h2>
      <p className="meta">
        {ctx.doc_id ? `Against ${ctx.step_id ?? `${ctx.doc_id} as a whole`}` : 'Not attached to a procedure.'}
      </p>
      <textarea
        className="input"
        rows={3}
        placeholder="What happened, in the words you would use out loud…"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <button className="primary" aria-busy={busy === 'deviation'} disabled={busy === 'deviation' || !text.trim()} onClick={() => void submit()}>
        {busy === 'deviation' ? 'Logging…' : 'Log deviation'}
      </button>

      {result && (
        <div className="row wrap result">
          <Pill tone="info">{result.deviation_id}</Pill>
          <Pill tone={result.notified ? 'ok' : 'warn'}>
            {result.notified ? 'Supervisor alerted' : 'Alert failed: tell your supervisor'}
          </Pill>
        </div>
      )}
      {error && (
        <p className="error-line" title={error.code}>
          {errorTitle(error.code)}. {error.message}
        </p>
      )}
    </section>
  );
}
