import { BrowserLensDisplay } from './display';
import type { FeedRequest, LiveDisplay } from './live-feed';
/** Shared read-only viewer for the portal and worker web app. */
export function mountLiveViewer(host: HTMLElement, request: FeedRequest, interval = 1000) {
  const root = document.createElement('div'); root.className = 'lens-simulator';
  const label = document.createElement('label'); label.textContent = 'Glasses device';
  const select = document.createElement('select'); select.setAttribute('aria-label', 'Glasses device'); label.append(select);
  const status = document.createElement('p'); status.className = 'lens-sim-note'; status.setAttribute('role', 'status');
  status.textContent = 'Connecting to glasses feed…';
  const display = new BrowserLensDisplay();
  const note = document.createElement('p'); note.className = 'lens-sim-note';
  note.textContent = 'Live display content acknowledged by the glasses app. Font rendering may differ on hardware.';
  root.append(label, status, display.element, note); host.append(root);
  let stopped = false, epoch = 0, revision = '', timer: ReturnType<typeof setTimeout>;
  const abort = new AbortController();
  const blank = () => { revision = ''; void display.render({ header: 'SPECS', main: '', footer: 'waiting for glasses' }, 'IDLE'); };
  select.onchange = () => { epoch++; blank(); root.dataset.live = 'false'; status.textContent = 'Connecting to selected glasses…'; };
  const tick = async () => {
    const current = epoch;
    try {
      const rows = await request<LiveDisplay[]>('/v1/lens/displays', { signal: abort.signal });
      if (stopped || current !== epoch) return;
      const previous = select.value;
      select.replaceChildren(...rows.map(row => {
        const option = document.createElement('option'); option.value = row.device_id;
        option.textContent = `${row.worker_name || 'Glasses'} · ${row.device_id.slice(0, 8)}${row.live ? ' · live' : ''}`; return option;
      }));
      select.value = rows.some(r => r.device_id === previous) ? previous : (rows.find(r => r.live)?.device_id ?? rows[0]?.device_id ?? '');
      if (select.value !== previous) blank();
      if (!rows.length) { blank(); root.dataset.live = 'false'; status.textContent = 'No glasses in this workspace. Join the same workspace on the glasses and open the updated Specs app.'; return; }
      const id = select.value;
      const frame = await request<LiveDisplay>(`/v1/lens/displays/${encodeURIComponent(id)}`, { signal: abort.signal });
      if (stopped || current !== epoch || select.value !== id) return;
      status.textContent = frame.live ? `Live from glasses · ${frame.screen?.toLowerCase().replaceAll('_', ' ') ?? ''}` :
        frame.last_seen ? `Offline or paused · last received ${new Date(frame.last_seen * 1000).toLocaleTimeString()}` : 'Waiting for glasses. Open the updated Specs app on the G2.';
      root.dataset.live = String(frame.live);
      const key = `${id}:${JSON.stringify([frame.screen, frame.frame, frame.diagram])}`;
      if (frame.frame && frame.screen && revision !== key) {
        await display.render(frame.frame, frame.screen, frame.diagram); revision = key;
      } else if (!frame.frame) blank();
    } catch (error) {
      if (!stopped && current === epoch) { blank(); root.dataset.live = 'false'; status.textContent = error instanceof Error ? error.message : 'Display feed disconnected. Retrying.'; }
    } finally { if (!stopped) timer = setTimeout(() => void tick(), interval); }
  };
  blank(); void tick();
  return { dispose() { stopped = true; epoch++; abort.abort(); clearTimeout(timer); display.dispose(); root.remove(); } };
}
