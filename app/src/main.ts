import { waitForEvenAppBridge, OsEventTypeList } from '@evenrealities/even_hub_sdk';
import type { AskRequest, AskResponse, Pairing, Assignment, DiagramImage, ProgressEvent } from './types';
import { LensController, restoreSession, serializeSession, STORAGE_KEY, type LensState, type LensPorts } from './state';
import { BridgeQueue } from './ui/bridge-queue';
import { LensDisplay, DiagramRenderError, type Layout } from './ui/layout';
import { renderScreen, type ScreenText } from './ui/screens';
import { gestureFromEvent } from './ui/input';
import { createLocalV2FixturePorts } from './ui/local-v2-stubs';
import { SessionStore } from './ui/session-store';
type HeadGesture = 'NOD' | 'SHAKE';
interface Runtime {
    audio: Pick<LensPorts, 'startCapture' | 'stopCapture'> & {
        isCapturing(): boolean;
    };
    api: Pick<LensPorts, 'ask'> & {
        pair(): Promise<Pairing>;
        pairingStatus(): Promise<Pairing>;
        nextAssignment(): Promise<Assignment | null>;
        reportProgress(ev: ProgressEvent): void;
        getDiagram(id: string): Promise<DiagramImage>;
    };
    motion: {
        startHeadGestures(cb: (g: HeadGesture) => void): Promise<void>;
        stopHeadGestures(): Promise<void>;
        calibrate(cb: (done: number, needed: number) => void): Promise<{
            ok: boolean;
        }>;
        isCalibrated(): boolean;
        simulateGesture(g: HeadGesture): void;
    };
    obs: {
        initObs(): unknown;
        startAsk(): {
            finishSpan(name: string): void;
            end(outcome: string): void;
        };
    };
}
const loaders = import.meta.glob('./{audio/capture,api/client,obs/sentry,motion/gestures}.ts');
const mock = import.meta.env.VITE_MOCK === '1';
const params = new URLSearchParams(location.search);
const dev = import.meta.env.DEV && (mock || params.get('dev') === '1');
const app = document.querySelector<HTMLDivElement>('#app')!;
const heading = document.createElement('h1');
heading.textContent = 'Margin';
const status = document.createElement('p');
status.textContent = 'Connecting...';
const mode = document.createElement('p');
const mirror = document.createElement('pre');
const controls = document.createElement('div');
controls.hidden = !dev;
const utterance = document.createElement('input');
utterance.id = 'dev-utterance';
utterance.value = 'question';
utterance.setAttribute('aria-label', 'Mock utterance');
const nod = document.createElement('button');
nod.id = 'dev-nod';
nod.textContent = 'Nod';
const shake = document.createElement('button');
shake.id = 'dev-shake';
shake.textContent = 'Shake';
controls.append(nod, shake);
if (mock)
    controls.append(' Mock utterance: ', utterance);
app.append(heading, status, mode, controls, mirror);
async function boot() {
    const bridge = await waitForEvenAppBridge(), queue = new BridgeQueue();
    const display = new LensDisplay({
        createStartUpPageContainer: p => queue.run(() => bridge.createStartUpPageContainer(p)),
        rebuildPageContainer: p => queue.run(() => bridge.rebuildPageContainer(p)),
        textContainerUpgrade: p => queue.run(() => bridge.textContainerUpgrade(p)),
        updateImageRawData: p => queue.run(() => bridge.updateImageRawData(p)),
    });
    await display.render({ header: 'MARGIN', main: '', footer: 'starting...' });
    const report = (error: unknown) => { console.warn('[Margin] integration failure', error instanceof Error ? error.message : 'unknown'); };
    const paths = ['./audio/capture.ts', './api/client.ts', './obs/sentry.ts', './motion/gestures.ts'];
    let io: Runtime;
    const hasV2 = paths.every(path => !!loaders[path]);
    if (!hasV2 && mock) {
        io = createLocalV2FixturePorts(() => utterance.value, params.get('scenario') ?? 'm1');
        mode.textContent = 'Temporary v2 UI mocks: synthetic commands, assignment, calibration and PNG tiles. No microphone, relay or IMU.';
    }
    else {
        if (!hasV2)
            throw new Error('Part 2 v2 motion/client modules are not installed; use mock mode for independent UI testing.');
        const [audio, api, obs, motion] = await Promise.all(paths.map(path => loaders[path]()));
        io = { audio, api, obs, motion } as Runtime;
        if (typeof io.api.pair !== 'function' || typeof io.motion.startHeadGestures !== 'function')
            throw new Error('Part 2 v2 interfaces are incomplete');
        mode.textContent = mock ? 'Part 2 v2 mocks' : 'Live mode';
    }
    await io.obs.initObs();
    const raw = await queue.run(() => bridge.getLocalStorage(STORAGE_KEY));
    const state = restoreSession(raw, Date.now(), crypto.randomUUID());
    state.calibrated = io.motion.isCalibrated();
    if (state.privacySeen && !state.calibrated)
        state.screen = 'CALIBRATE';
    const store = new SessionStore(value => queue.run(() => bridge.setLocalStorage(STORAGE_KEY, value)), raw);
    let foreground = true, closing = false, motionOn = false;
    let motionWork = Promise.resolve();
    const syncMotion = (value: LensState) => {
        const wanted = foreground && value.privacySeen && value.calibrated;
        if (wanted === motionOn)
            return;
        motionOn = wanted;
        motionWork = motionWork.then(() => queue.run(() => wanted ? io.motion.startHeadGestures(g => controller.dispatch({ type: g })) : io.motion.stopHeadGestures())).catch(error => { motionOn = false; report(error); });
    };
    let pending: {
        text: ScreenText;
        layout: Layout;
        diagram?: DiagramImage;
        screen: string;
        page: number;
        step: number | string;
    } | null = null, rendering: Promise<void> | null = null;
    const render: LensPorts['render'] = (value, level, diagram) => {
        const text = renderScreen(value, level), layout = value.screen === 'DIAGRAM' ? 'DIAGRAM' : 'TEXT';
        pending = { text, layout, diagram, screen: value.screen, page: value.page, step: value.walkthrough?.index ?? '-' };
        status.textContent = value.screen;
        app.dataset.screen = value.screen;
        mirror.textContent = [text.header, text.main, text.footer].join('\n\n');
        console.info(`[Margin] screen=${value.screen} page=${value.page} step=${value.walkthrough?.index ?? '-'} assignment=${!!value.assignment_id}`);
        syncMotion(value);
        if (!rendering)
            rendering = (async () => {
                while (pending) {
                    const next = pending;
                    pending = null;
                    try {
                        await display.render(next.text, next.layout, next.diagram);
                    }
                    catch (error) {
                        if (error instanceof DiagramRenderError && controller.state.diagramId) {
                            controller.dispatch({ type: 'DIAGRAM_FAILED', id: controller.state.diagramId });
                            continue;
                        }
                        else
                            throw error;
                    }
                    console.info(`[Margin] rendered screen=${next.screen} page=${next.page} step=${next.step} rebuilds=${display.rebuildCount}`);
                }
            })().finally(() => { rendering = null; });
        return rendering;
    };
    let assignmentBusy = false;
    const poll = async () => {
        if (!foreground || closing || assignmentBusy || controller.state.screen !== 'IDLE' || controller.state.assignment_id || !controller.state.pairing?.claimed)
            return;
        assignmentBusy = true;
        try {
            const assignment = await io.api.nextAssignment();
            if (assignment && foreground && controller.state.screen === 'IDLE')
                controller.dispatch({ type: 'ASSIGNMENT', assignment, now: Date.now() });
        }
        catch (error) {
            report(error);
        }
        finally {
            assignmentBusy = false;
        }
    };
    const ports: LensPorts = {
        now: Date.now, onError: report, render, persist: value => store.save(serializeSession(value)),
        exit: async () => { await store.flush(); console.info('[Margin] native exit confirmation requested'); if (!await queue.run(() => bridge.shutDownPageContainer(1)))
            throw new Error('Native exit failed'); console.info('[Margin] native exit accepted'); },
        startCapture: (onLevel, onEndpoint) => queue.run(() => io.audio.startCapture(onLevel, onEndpoint)),
        stopCapture: () => queue.run(() => io.audio.stopCapture()),
        ask: async (req: AskRequest, opts): Promise<AskResponse> => { const span = io.obs.startAsk(); try {
            const answer = await io.api.ask(req, opts);
            span.end(answer.outcome);
            return answer;
        }
        catch (error) {
            span.end('error');
            throw error;
        } },
        reportProgress: ev => io.api.reportProgress(ev),
        // Controller prefetches current + next on every step change, using Part 2's cache.
        getDiagram: id => io.api.getDiagram(id), pollAssignment: () => { void poll(); },
        calibrate: onProgress => io.motion.calibrate(onProgress),
    };
    const controller = new LensController(state, ports);
    await controller.start();
    nod.onclick = () => io.motion.simulateGesture('NOD');
    shake.onclick = () => io.motion.simulateGesture('SHAKE');
    let pairingBusy = false;
    const checkPairing = async () => {
        if (!foreground || closing || pairingBusy || controller.state.pairing?.claimed)
            return;
        pairingBusy = true;
        try {
            controller.dispatch({ type: 'PAIRED', pairing: await io.api.pairingStatus() });
        }
        catch (error) {
            report(error);
        }
        finally {
            pairingBusy = false;
        }
    };
    try {
        controller.dispatch({ type: 'PAIRED', pairing: await io.api.pair() });
    }
    catch (error) {
        report(error);
        controller.dispatch({ type: 'FAIL' });
    }
    let pairTimer: ReturnType<typeof setInterval> | undefined, assignmentTimer: ReturnType<typeof setInterval> | undefined;
    const startPolling = () => { clearInterval(pairTimer); clearInterval(assignmentTimer); pairTimer = setInterval(() => { void checkPairing(); }, 1000); assignmentTimer = setInterval(() => { void poll(); }, 10000); void poll(); };
    const suspend = async () => { foreground = false; clearInterval(pairTimer); clearInterval(assignmentTimer); syncMotion(controller.state); const saved = controller.suspend(); await store.flush(); await saved; await motionWork; };
    const resume = async () => { foreground = true; await controller.resume(); syncMotion(controller.state); startPolling(); };
    const unsubscribe = bridge.onEvenHubEvent(event => {
        const type = event.sysEvent?.eventType;
        if (type === OsEventTypeList.FOREGROUND_ENTER_EVENT) {
            void resume().catch(report);
            return;
        }
        if (type === OsEventTypeList.FOREGROUND_EXIT_EVENT) {
            void suspend().catch(report);
            return;
        }
        if (type === OsEventTypeList.SYSTEM_EXIT_EVENT || type === OsEventTypeList.ABNORMAL_EXIT_EVENT) {
            void cleanup();
            return;
        }
        const gesture = gestureFromEvent(event, controller.state.screen === 'DIAGRAM' ? 3 : 2);
        if (gesture)
            controller.dispatch({ type: gesture });
    });
    const visibility = () => { void (document.hidden ? suspend() : resume()).catch(report); };
    document.addEventListener('visibilitychange', visibility);
    async function cleanup() { if (closing)
        return; closing = true; foreground = false; clearInterval(pairTimer); clearInterval(assignmentTimer); unsubscribe(); document.removeEventListener('visibilitychange', visibility); syncMotion(controller.state); await controller.dispose().catch(report); await store.flush().catch(report); await motionWork; }
    window.addEventListener('pagehide', () => { void cleanup(); }, { once: true });
    if (import.meta.hot)
        import.meta.hot.dispose(() => { void cleanup(); });
    startPolling();
}
void boot().catch(error => { console.error('[Margin] boot failed', error); status.textContent = 'Unable to start. ' + String(error); });
