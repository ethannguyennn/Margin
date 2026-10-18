import type { AskResponse, Citation } from '../contract';

/** The phone's reading surface: the answer block, then the evidence behind it. */
export function AnswerDetail({ res }: { res: AskResponse }) {
  return (
    <>
      <section className="card">
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
    </>
  );
}

function CitationItem({ citation }: { citation: Citation }) {
  return (
    <li>
      <p className="lbl">
        {citation.doc_id} rev {citation.revision} · section {citation.section}
      </p>
      <p className="quote">{citation.quote}</p>
    </li>
  );
}
