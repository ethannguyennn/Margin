// Browser host and bridge boot derived from evenhub-templates/asr.
import { waitForEvenAppBridge, OsEventTypeList } from '@evenrealities/even_hub_sdk';
import type { AskRequest, AskResponse } from './types';
import { LensController, restoreSession, serializeSession, STORAGE_KEY, type LensState, type LensPorts } from './state';
import { BridgeQueue } from './ui/bridge-queue';
import { LensDisplay } from './ui/layout';
import { renderScreen, type ScreenText } from './ui/screens';
import { gestureFromEvent } from './ui/input';
import { FIXTURE_NAMES, UI_FIXTURES } from './ui/fixtures';

type CaptureModule = Pick<LensPorts, 'startCapture' | 'stopCapture'> & { isCapturing(): boolean };
type ClientModule = Pick<LensPorts, 'ask'>;
interface ObsModule { initObs(): void; startAsk(): { finishSpan(name: string): void; end(outcome: string): void }; }
// Part 2 owns these frozen paths. The live path fails closed until they land.
const modules = import.meta.glob('./{audio/capture,api/client,obs/sentry}.ts');
const isMock = import.meta.env.VITE_MOCK === '1';
const app = document.querySelector<HTMLDivElement>('#app')!;
const title = document.createElement('h1'); title.textContent = 'Margin';
const status = document.createElement('p'); status.textContent = 'Connecting to Even G2...';
const mode = document.createElement('p'); mode.textContent = isMock ? 'Synthetic UI fixtures. No microphone or network.' : 'Live mode: Part 2 audio and relay integration.';
const mirror = document.createElement('pre');
app.append(title, status, mode, mirror);

async function boot(): Promise<void> {
  const bridge = await waitForEvenAppBridge();
  const queue = new BridgeQueue();
  const display = new LensDisplay({
    createStartUpPageContainer: payload => queue.run(() => bridge.createStartUpPageContainer(payload)),
    textContainerUpgrade: payload => queue.run(() => bridge.textContainerUpgrade(payload)),
  });
  const report = (error: unknown) => {
    console.error('[Margin]', error);
    status.textContent = 'Connection or integration error. Reopen the app to reconnect.';
  };
  let pending: ScreenText | null = null;
  let rendering: Promise<void> | null = null;
  const render = (state: LensState, level: number): Promise<void> => {
    const text = renderScreen(state, level); pending = text;
    mirror.textContent = [text.header, text.main, text.footer].join('\n\n');
    status.textContent = state.screen;
    console.info(`[Margin] screen=${state.screen} page=${state.page} step=${state.walkthrough?.index ?? '-'} verified=${state.response?.verified ?? '-'}`);
    if (!rendering) rendering = (async () => {
      while (pending) { const next = pending; pending = null; await display.render(next); }
    })().finally(() => { rendering = null; });
    return rendering;
  };
  // Startup happens once and before storage or audio calls.
  await display.render({ header: 'MARGIN', main: '', footer: 'starting...' });
  const raw = await queue.run(() => bridge.getLocalStorage(STORAGE_KEY));
  const state = restoreSession(raw, Date.now(), crypto.randomUUID());
  let saved = raw;
  const persist = async (value: LensState) => {
    const encoded = serializeSession(value);
    if (encoded === saved) return;
    await queue.run(async () => {
      if (encoded === saved) return;
      if (!await bridge.setLocalStorage(STORAGE_KEY, encoded)) throw new Error('Session storage failed');
      saved = encoded;
    });
  };
  let fixtureIndex = 0;
  let integrations: Promise<[CaptureModule, ClientModule, ObsModule]> | null = null;
  const loadIntegrations = () => integrations ??= (async (): Promise<[CaptureModule, ClientModule, ObsModule]> => {
    const paths = ['./audio/capture.ts', './api/client.ts', './obs/sentry.ts'];
    if (paths.some(path => !modules[path])) throw new Error('Part 2 integration modules are not installed. Use npm run dev:mock for the fixture demo.');
    const [audio, client, obs] = await Promise.all(paths.map(path => modules[path]()));
    const result: [CaptureModule, ClientModule, ObsModule] = [audio as CaptureModule, client as ClientModule, obs as ObsModule];
    result[2].initObs(); return result;
  })();
  const ports: LensPorts = {
    render, persist, now: Date.now, onError: report,
    exit: async () => {
      console.info('[Margin] native exit confirmation requested');
      if (!await queue.run(() => bridge.shutDownPageContainer(1))) throw new Error('Exit dialog failed');
      console.info('[Margin] native exit accepted');
    },
    startCapture: async onLevel => {
      if (isMock) { onLevel(0.5); return; }
      const [audio] = await loadIntegrations(); await queue.run(() => audio.startCapture(onLevel));
    },
    stopCapture: async () => {
      if (isMock || !integrations) return { data_b64: '', sample_rate: 16000 };
      const [audio] = await integrations;
      return audio.isCapturing() ? queue.run(() => audio.stopCapture()) : { data_b64: '', sample_rate: 16000 };
    },
    ask: async (request: AskRequest, opts): Promise<AskResponse> => {
      if (isMock) {
        // UI fixture adapter only; no audio/relay/mock module is implemented here.
        const name = FIXTURE_NAMES[fixtureIndex++ % FIXTURE_NAMES.length];
        await new Promise<void>((resolve, reject) => {
          const timer = setTimeout(resolve, 600);
          opts?.signal?.addEventListener('abort', () => { clearTimeout(timer); reject(new DOMException('Cancelled', 'AbortError')); }, { once: true });
        });
        console.info(`[Margin] UI fixture=${name}`); return structuredClone(UI_FIXTURES[name]);
      }
      const [, client, obs] = await loadIntegrations(); const span = obs.startAsk();
      try { const result = await client.ask(request, opts); span.end(result.outcome); return result; }
      catch (error) { span.end('error'); throw error; }
    },
  };
  const controller = new LensController(state, ports);
  await controller.start(); await persist(state);
  let levelTick = 0;
  const originalRender = ports.render;
  ports.render = (value, level) => {
    if (value.screen === 'LISTENING' && level > 0 && Date.now() - levelTick < 120) return Promise.resolve();
    if (level > 0) levelTick = Date.now();
    return originalRender(value, level);
  };
  let closing = false;
  const unsubscribe = bridge.onEvenHubEvent(event => {
    const sys = event.sysEvent?.eventType;
    if (sys === OsEventTypeList.FOREGROUND_ENTER_EVENT) { void controller.resume().catch(report); return; }
    if (sys === OsEventTypeList.FOREGROUND_EXIT_EVENT) { void controller.suspend().catch(report); return; }
    if (sys === OsEventTypeList.SYSTEM_EXIT_EVENT || sys === OsEventTypeList.ABNORMAL_EXIT_EVENT) { void cleanup(); return; }
    const gesture = gestureFromEvent(event);
    if (gesture) controller.dispatch({ type: gesture });
  });
  const visibility = () => { void (document.hidden ? controller.suspend() : controller.resume()).catch(report); };
  document.addEventListener('visibilitychange', visibility);
  async function cleanup() {
    if (closing) return;
    closing = true; unsubscribe(); document.removeEventListener('visibilitychange', visibility);
    await controller.dispose().catch(report);
  }
  window.addEventListener('pagehide', () => { void cleanup(); }, { once: true });
  if (import.meta.hot) import.meta.hot.dispose(() => { void cleanup(); });
}
void boot().catch(error => { console.error('[Margin] boot failed', error); status.textContent = `Unable to start: ${String(error)}`; });
