import type { AskResponse, Latency } from '../contract';

const STAGES: Array<keyof Latency> = ['stt', 'embed', 'retrieve', 'generate', 'verify', 'total'];

/** Where the time went — one stage per row, the total in full ink. */
export function LatencyPanel({ res }: { res: AskResponse }) {
  return (
    <section className="card">
      <h2 className="section-title">Latency</h2>
      <table>
        <tbody>
          {STAGES.map((stage) => (
            <tr key={stage} className={stage === 'total' ? 'tot' : undefined}>
              <td>{stage}</td>
              <td>{res.latency_ms[stage]} ms</td>
            </tr>
          ))}
        </tbody>
      </table>
      {res.trace_id && <p className="meta mono">trace {res.trace_id}</p>}
    </section>
  );
}
