import type { AskResponse, Citation, Latency, Step } from '../contract';
import { OutcomePill, Pill, VerifiedPill } from './Pills';
import { Walkthrough } from './Walkthrough';
import { parseDisplay } from '../../ui/generated-display';
import { answerGraphic } from '../../ui/sop-graphics';
import { SopGraphic } from './SopGraphic';

const STAGES: Array<keyof Latency> = ['stt', 'embed', 'retrieve', 'generate', 'verify', 'total'];

/** The phone's reading surface: everything the glance line had to leave out. */
export function AnswerDetail({
  res,
  pinnedStepId,
  onUseStep,
}: {
  res: AskResponse;
  pinnedStepId: string | null;
  onUseStep: (step: Step) => void;
}) {
  const display = res.outcome === 'answered' && res.verified ? parseDisplay(res.display) : null;
  return (
    <div className="stack">
      <section className="card">
        <div className="row wrap">
          <OutcomePill outcome={res.outcome} />
          <Pill tone="muted">{res.intent}</Pill>
          {res.outcome === 'answered' && <VerifiedPill verified={res.verified} />}
        </div>
        <SopGraphic graphic={answerGraphic(res)} />
        {display && display.kind !== 'answer' && (
          <section className={`generated-card ${display.kind}`} aria-label={display.kind === 'warning' ? 'SOP warning' : 'SOP checklist'}>
            <h2 className="section-title">{display.kind === 'warning' ? 'Warning' : 'Checklist'}</h2>
            <ul className="list">
              {display.items.map((item, index) => (
                <li key={index} className="body">
                  {display.kind === 'checklist' && <span aria-hidden="true">□ </span>}{item}
                </li>
              ))}
            </ul>
          </section>
        )}
        <p className="glance">{res.glance || '—'}</p>
        {res.body && <p className="body">{res.body}</p>}
        {res.transcript && <p className="meta">Asked · “{res.transcript}”</p>}
        {res.source && <p className="meta">Source · {res.source}</p>}
        {res.error && (
          <p className="error-line">
            {res.error.code} · {res.error.message}
          </p>
        )}
      </section>

      {res.citations.length > 0 && (
        <section className="card">
          <div className="row between">
            <h2 className="section-title">Citations</h2>
            <span className="meta">{res.citations.length}</span>
          </div>
          <ul className="list quotes">
            {res.citations.map((c) => (
              <CitationItem key={c.chunk_id} citation={c} />
            ))}
          </ul>
        </section>
      )}

      {res.walkthrough && res.walkthrough.steps.length > 0 && (
        <Walkthrough
          key={`${res.walkthrough.doc_id}-${res.trace_id}`}
          wt={res.walkthrough}
          pinnedStepId={pinnedStepId}
          onUse={onUseStep}
        />
      )}

      <section className="card">
        <h2 className="section-title">Latency</h2>
        <div className="row wrap">
          {STAGES.map((stage) => (
            <span key={stage} className={`chip static${stage === 'total' ? ' strong' : ''}`}>
              {stage} {res.latency_ms[stage]} ms
            </span>
          ))}
        </div>
        {res.trace_id && <p className="meta mono">trace {res.trace_id}</p>}
      </section>
    </div>
  );
}

function CitationItem({ citation }: { citation: Citation }) {
  return (
    <li>
      <p className="meta">
        {citation.doc_id} rev {citation.revision} · section {citation.section}
      </p>
      <p className="quote">{citation.quote}</p>
    </li>
  );
}
