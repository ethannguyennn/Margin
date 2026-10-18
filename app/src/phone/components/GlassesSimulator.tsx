import { useEffect, useRef } from 'react';
import { ask, getDiagram } from '../../api/client';
import { BrowserLensDisplay } from '../../simulator/display';
import { mountSimulator } from '../../simulator/simulator';
import { useStore } from '../store';

export function GlassesSimulator() {
  const { lens, sessionId, state, recordSimulatorAnswer } = useStore();
  const host = useRef<HTMLDivElement>(null);
  const display = useRef<BrowserLensDisplay | null>(null);
  const context = useRef(state.context); context.current = state.context;
  useEffect(() => {
    if (!host.current) return;
    if (lens.connected) {
      const mirror = new BrowserLensDisplay(); display.current = mirror;
      host.current.append(mirror.element);
      return () => { mirror.dispose(); mirror.element.remove(); display.current = null; };
    }
    const simulator = mountSimulator(host.current, {
      sessionId, ask, getDiagram, context: () => context.current, onExchange: recordSimulatorAnswer,
    });
    return () => simulator.dispose();
  }, [lens.connected, sessionId, recordSimulatorAnswer]);
  useEffect(() => {
    if (!display.current || !lens.connected) return;
    const frame = lens.frame ?? { header: lens.screen ?? '', main: lens.lensText, footer: '', graphic_id: lens.graphic_id };
    void display.current.render(frame, lens.screen ?? 'IDLE', lens.diagram).catch(() => {});
  }, [lens]);
  return (
    <section className="card">
      <h2 className="section-title">Glasses display</h2>
      {lens.connected && <div className="lens-sim-bar"><span>Live from glasses</span><span>{lens.screen?.toLowerCase().replaceAll('_', ' ')}</span></div>}
      <div ref={host} />
      <p className="lens-sim-note">576 × 288 per eye · font rendering may differ on hardware.</p>
    </section>
  );
}
