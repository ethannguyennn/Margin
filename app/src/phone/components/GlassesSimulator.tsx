import { useEffect, useRef, useState } from 'react';
import { ask, getDiagram } from '../../api/client';
import { BrowserLensDisplay } from '../../simulator/display';
import { mountSimulator } from '../../simulator/simulator';
import { useStore } from '../store';
import { mountLiveViewer } from '../../simulator/live-viewer';
import { deviceFeedRequest } from '../../simulator/device-feed';

export function GlassesSimulator() {
  const { lens, sessionId, state, recordSimulatorAnswer } = useStore();
  const [mode, setMode] = useState<'live' | 'simulate'>('live');
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
    if (mode === 'live') {
      const viewer = mountLiveViewer(host.current, deviceFeedRequest);
      return () => viewer.dispose();
    }
    const simulator = mountSimulator(host.current, {
      sessionId, ask, getDiagram, context: () => context.current, onExchange: recordSimulatorAnswer,
    });
    return () => simulator.dispose();
  }, [lens.connected, sessionId, recordSimulatorAnswer, mode]);
  useEffect(() => {
    if (!display.current || !lens.connected) return;
    const frame = lens.frame ?? { header: lens.screen ?? '', main: lens.lensText, footer: '', graphic_id: lens.graphic_id };
    void display.current.render(frame, lens.screen ?? 'IDLE', lens.diagram).catch(() => {});
  }, [lens]);
  return (
    <section className="card">
      <h2 className="section-title">Glasses display</h2>
      {!lens.connected && <div className="lens-sim-actions">
        <button className="ghost" type="button" aria-pressed={mode === 'live'} onClick={() => setMode('live')}>Live glasses</button>
        <button className="ghost" type="button" aria-pressed={mode === 'simulate'} onClick={() => setMode('simulate')}>Browser simulation</button>
      </div>}
      {lens.connected && <div className="lens-sim-bar"><span>Live from glasses</span><span>{lens.screen?.toLowerCase().replaceAll('_', ' ')}</span></div>}
      <div ref={host} />
      {lens.connected && <p className="lens-sim-note">After joining a workspace, this display is shared live with that workspace while Specs is open.</p>}
      <p className="lens-sim-note">576 × 288 per eye · font rendering may differ on hardware.</p>
    </section>
  );
}
