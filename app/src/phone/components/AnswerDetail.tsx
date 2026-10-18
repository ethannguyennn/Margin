import { answerGraphic } from '../../ui/sop-graphics';
import { SopGraphic } from './SopGraphic';
import type { AskResponse, Citation, Latency, Step } from '../contract';
import { errorTitle, seconds } from '../copy';
import { ChevronIcon } from './Icons';
import { OutcomePill, Pill, VerifiedPill } from './Pills';
import { Walkthrough } from './Walkthrough';

const STAGES: Array<keyof Latency> = ['stt', 'embed', 'retrieve', 'generate', 'verify'];
const STAGE_LABEL: Record<keyof Latency, string> = {
  stt: 'Speech to text',
  embed: 'Embedding',
  retrieve: 'Search',
  generate: 'Writing the answer',
  verify: 'Citation check',
  total: 'Total',
};

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
  return (
    <div className="stack">
      <section className="card">
        <div className="row wrap">
          <OutcomePill outcome={res.outcome} />
          <Pill tone="muted">{res.intent}</Pill>
          {res.outcome === 'answered' && <VerifiedPill verified={res.verified} />}
        </div>
        <p className="glance">{res.glance || '—'}</p>
        {res.body && <p className="body">{res.body}</p>}
        <SopGraphic graphic={answerGraphic(res)} />
        {res.transcript && <p className="meta">Asked · “{res.transcript}”</p>}
        {res.source && <p className="meta">Source · {res.source}</p>}
        {res.error && (
          <p className="error-line" title={res.error.code}>
            {errorTitle(res.error.code)}. {res.error.message}
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

      <details className="disclosure card-disclosure">
        <summary>
          Answered in {seconds(res.latency_ms.total)}
          <ChevronIcon size={14} className="disclosure-chev" />
        </summary>
        <dl className="details-list">
          {STAGES.map((stage) => (
            <div key={stage} className="details-pair">
              <dt>{STAGE_LABEL[stage]}</dt>
              <dd className="num">{res.latency_ms[stage]} ms</dd>
            </div>
          ))}
          {res.trace_id && (
            <div className="details-pair">
              <dt>Trace ID</dt>
              <dd>{res.trace_id}</dd>
            </div>
          )}
        </dl>
      </details>
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
