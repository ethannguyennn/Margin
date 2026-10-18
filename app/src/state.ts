import type { AskRequest, AskResponse, Assignment, Clarify, Command, DiagramImage, Pairing, ProgressEvent, ProgressKind, Walkthrough } from './types';
import { answerGraphic, stepGraphic, ILLUSTRATED_PAGE_CHARS } from './ui/sop-graphics';
import { sanitizeForG2 } from './ui/glyphs';
import { BODY_PAGE_CHARS, paginate } from './ui/paginate';
export const GLANCE_TIMEOUT_MS = 20000;
export const INACTIVITY_TIMEOUT_MS = 60000;
export const WALKTHROUGH_TTL_MS = 30 * 60000;
export const ASSIGNMENT_TTL_MS = 12 * 60 * 60000;
export const STORAGE_KEY = 'specs.session.v1'; // migrate existing v1 values in place
export const SCREENS = ['PRIVACY', 'CALIBRATE', 'PAIRING', 'IDLE', 'TASK_READY', 'STEP', 'STEP_DETAILS', 'DIAGRAM', 'TASK_DONE', 'LISTENING', 'THINKING', 'ANSWER_GLANCE', 'ANSWER_EXPANDED', 'NOT_FOUND', 'CLARIFY', 'WALKTHROUGH', 'LOGGED', 'ERROR'] as const;
export type Screen = typeof SCREENS[number];
export type Gesture = 'PRESS' | 'DOUBLE_PRESS' | 'UP' | 'DOWN' | 'LONG_PRESS' | 'NOD' | 'SHAKE';
export type Action = {
    type: Gesture | 'TIMEOUT' | 'DISMISS' | 'ENDPOINT' | 'EMPTY_CAPTURE';
} | {
    type: 'RESPONSE';
    response: AskResponse;
    now: number;
} | {
    type: 'FAIL';
} | {
    // A question typed on the phone screen: same THINKING -> answer path as speech.
    type: 'TEXT_ASK';
} | {
    type: 'ASSIGNMENT';
    assignment: Assignment;
    now?: number;
} | {
    type: 'PAIRED';
    pairing: Pairing;
} | {
    type: 'CALIBRATED';
    ok: boolean;
} | {
    type: 'CALIBRATION_PROGRESS';
    done: number;
    needed: number;
} | {
    type: 'DIAGRAM_READY' | 'DIAGRAM_FAILED';
    id: string;
};
export type Effect = 'START_CAPTURE' | 'STOP_AND_SEND' | 'SEND_TEXT' | 'CANCEL' | 'EXIT' | 'PREFETCH_DIAGRAMS' | 'POLL_ASSIGNMENT' | 'CALIBRATE' | {
    type: 'REPORT_PROGRESS';
    kind: ProgressKind;
    step_id: string | null;
} | {
    type: 'SHOW_DIAGRAM';
    diagram_id: string;
};
export interface AskContext { doc_id: string | null; step_id: string | null; assignment_id?: string | null; }
/** Typed asks are refused here: one ask in flight, privacy first, setup screens own the lens. */
export const TEXT_ASK_BLOCKED: Screen[] = ['THINKING', 'PRIVACY', 'CALIBRATE'];
export interface LensState {
    screen: Screen;
    session_id: string;
    privacySeen: boolean;
    micSource: 'glasses' | 'phone';
    response: AskResponse | null;
    walkthrough: Walkthrough | null;
    walkthroughReceivedAt: number;
    pages: string[];
    page: number;
    detailReturn: 'ANSWER_GLANCE' | 'WALKTHROUGH';
    returnTo: Screen;
    returnState: LensState | null;
    calibrated: boolean;
    calibrationDone: number;
    calibrationNeeded: number;
    pairing: Pick<Pairing, 'pair_code' | 'claimed' | 'worker_name'> | null;
    assignment_id: string | null;
    assignedAt: number;
    taskPaused: boolean;
    taskStarted: boolean;
    diagramId: string | null;
    diagramReady: boolean;
    notice: string;
}
export interface Transition {
    state: LensState;
    effects: Effect[];
}
export function initialState(sessionId: string): LensState {
    return { screen: 'PRIVACY', session_id: sessionId, privacySeen: false, micSource: 'glasses', response: null,
        walkthrough: null, walkthroughReceivedAt: 0, pages: [''], page: 0, detailReturn: 'ANSWER_GLANCE', returnTo: 'IDLE', returnState: null,
        calibrated: false, calibrationDone: 0, calibrationNeeded: 3, pairing: null, assignment_id: null, assignedAt: 0, taskPaused: false, taskStarted: false,
        diagramId: null, diagramReady: false, notice: '' };
}
const result = (state: LensState, effects: Effect[] = []): Transition => ({ state, effects });
const isStep = (s: Screen) => ['STEP', 'WALKTHROUGH', 'STEP_DETAILS', 'DIAGRAM'].includes(s);
const taskDestination = (s: LensState): Screen => !s.walkthrough ? 'IDLE' : s.assignment_id && !s.taskStarted ? 'TASK_READY' : 'STEP';
function idle(s: LensState): LensState {
    return { ...s, screen: 'IDLE', response: null, returnState: null, returnTo: 'IDLE', pages: [''], page: 0, notice: '', diagramId: null, diagramReady: false,
        ...(s.assignment_id && s.screen !== 'TASK_DONE' ? { taskPaused: true } : { walkthrough: null, walkthroughReceivedAt: 0, assignment_id: null, assignedAt: 0, taskStarted: false }) };
}
function back(s: LensState): LensState {
    if (s.screen === 'TASK_DONE')
        return idle(s);
    if (s.returnState)
        return { ...s.returnState, returnState: s.returnState.returnState, notice: '' };
    return s.returnTo === 'STEP' && s.walkthrough ? { ...s, screen: 'STEP', response: null, page: 0, notice: '' } : idle(s);
}
function failure(s: LensState): LensState { return { ...s, screen: 'ERROR', response: null, notice: '' }; }
function listen(s: LensState): Transition {
    return result({ ...s, screen: 'LISTENING', returnTo: s.screen, returnState: s, notice: '' }, ['START_CAPTURE']);
}
export function validWalkthrough(value: unknown): value is Walkthrough {
    if (!value || typeof value !== 'object')
        return false;
    const w = value as Walkthrough;
    return typeof w.doc_id === 'string' && !!w.doc_id && typeof w.revision === 'string' && typeof w.title === 'string' &&
        Array.isArray(w.steps) && w.steps.length > 0 && w.steps.length === w.total && Number.isInteger(w.index) && w.index >= 0 && w.index < w.total &&
        w.steps.every(s => s && [s.step_id, s.label, s.glance, s.body].every(v => typeof v === 'string') && !!s.glance && !!s.body &&
            [s.warning, s.checkpoint].every(v => v == null || typeof v === 'string') &&
            (!s.diagram || (typeof s.diagram.diagram_id === 'string' && typeof s.diagram.alt === 'string' && s.diagram.width === 576 && s.diagram.height === 144))) &&
        (w.scope == null || (Number.isInteger(w.scope.start) && Number.isInteger(w.scope.end) &&
            0 <= w.scope.start && w.scope.start <= w.index && w.index < w.scope.end && w.scope.end <= w.total));
}
/** The steps the worker is working through: the relay's scope, else the whole procedure. */
export function scopeOf(w: Walkthrough): { start: number; end: number } {
    return { start: w.scope?.start ?? 0, end: w.scope?.end ?? w.total };
}
/** A clarify the lens can show (BUILD-PLAN-V3 §2), sanitized; null falls back to NOT_FOUND. */
export function validClarify(r: AskResponse): Clarify | null {
    const c = r.clarify;
    if (r.outcome !== 'not_found' || r.needs_clarification !== true || !c || typeof c.prompt !== 'string' || !Array.isArray(c.options))
        return null;
    const prompt = sanitizeForG2(c.prompt).trim(), options = c.options.map(o => typeof o === 'string' ? sanitizeForG2(o).trim() : '');
    if (!prompt || prompt.length > 40 || options.length < 2 || options.length > 3 || options.some(o => !o || o.length > 24))
        return null;
    return { prompt, options };
}
// Screens that show one exchange. An answer asked from one of them returns past it to the screen
// the worker was working on (the STEP), not to the previous answer or the clarify prompt.
const EXCHANGE: Screen[] = ['ANSWER_GLANCE', 'ANSWER_EXPANDED', 'NOT_FOUND', 'CLARIFY', 'ERROR', 'LOGGED'];
function settled(s: LensState): LensState {
    let r = s.returnState;
    while (r && EXCHANGE.includes(r.screen) && r.returnState)
        r = r.returnState;
    return r === s.returnState ? s : { ...s, returnState: r, returnTo: r!.screen };
}
function preflight(w: Walkthrough): void { w.steps.forEach(s => paginate(sanitizeForG2(s.body), stepGraphic(s) ? ILLUSTRATED_PAGE_CHARS : BODY_PAGE_CHARS)); }
function progress(s: LensState, kind: ProgressKind, step_id: string | null): Effect[] {
    return s.assignment_id ? [{ type: 'REPORT_PROGRESS', kind, step_id }] : [];
}
function step(s: LensState, index = s.walkthrough?.index ?? 0): LensState {
    return { ...s, screen: 'STEP', walkthrough: s.walkthrough ? { ...s.walkthrough, index } : null, response: null,
        pages: [''], page: 0, returnState: null, returnTo: 'STEP', diagramId: null, diagramReady: false, notice: '', taskPaused: false };
}
function command(s: LensState, c: Command): Transition {
    const w = s.walkthrough, current = w?.steps[w.index];
    if (c === 'exit')
        return result(s, ['EXIT']);
    if (s.screen === 'TASK_DONE')
        return result(s);
    if (c === 'pause')
        return result(idle(s), [...progress(s, 'task_paused', current?.step_id ?? null), 'CANCEL', 'POLL_ASSIGNMENT']);
    if (!w || !current)
        return result({ ...s, notice: 'No active task' });
    if (s.assignment_id && !s.taskStarted) {
        if (c === 'resume')
            return result({ ...step(s), taskStarted: true }, [...progress(s, 'task_started', null), ...progress(s, 'step_started', current.step_id), 'PREFETCH_DIAGRAMS']);
        return result({ ...s, screen: 'TASK_READY', notice: '' });
    }
    if (c === 'resume' || c === 'repeat')
        return result(step(s), ['PREFETCH_DIAGRAMS']);
    if (c === 'details')
        return result({ ...step(s), screen: 'STEP_DETAILS', pages: paginate(sanitizeForG2(current.body), stepGraphic(current) ? ILLUSTRATED_PAGE_CHARS : BODY_PAGE_CHARS) });
    if (c === 'diagram') {
        // No relay diagram: the step's reference picture is shown beside its details instead.
        if (!current.diagram)
            return stepGraphic(current) ? command(s, 'details') : result({ ...step(s), notice: 'No diagram for this step' });
        return result({ ...step(s), screen: 'DIAGRAM', diagramId: current.diagram.diagram_id }, [{ type: 'SHOW_DIAGRAM', diagram_id: current.diagram.diagram_id }]);
    }
    if (c === 'back') {
        const index = Math.max(scopeOf(w).start, w.index - 1);
        return result(step(s, index), [...(index !== w.index ? progress(s, 'step_started', w.steps[index].step_id) : []), 'PREFETCH_DIAGRAMS']);
    }
    if (c === 'next') {
        const effects = progress(s, 'step_completed', current.step_id);
        if (w.index + 1 >= scopeOf(w).end)
            return result({ ...step(s), screen: 'TASK_DONE' }, [...effects, ...progress(s, 'task_completed', null)]);
        return result(step(s, w.index + 1), [...effects, ...progress(s, 'step_started', w.steps[w.index + 1].step_id), 'PREFETCH_DIAGRAMS']);
    }
    return result(s);
}
const commands: Command[] = ['next', 'back', 'repeat', 'details', 'diagram', 'pause', 'resume', 'exit'];
function receive(origin: LensState, r: AskResponse, now: number): Transition {
    const s = settled(origin);
    if (r.outcome === 'command')
        return r.command && commands.includes(r.command) ? command(back(s), r.command) : result(failure(s));
    if (r.outcome === 'not_found') {
        const clarify = validClarify(r);
        return result({ ...s, screen: clarify ? 'CLARIFY' : 'NOT_FOUND', response: clarify ? { ...r, clarify } : null });
    }
    if (r.outcome === 'error' || r.verified !== true)
        return result({ ...failure(s), notice: r.outcome === 'error' && r.error?.message === 'Busy, try again' ? 'Busy, try again' : '' });
    try {
        if (r.walkthrough !== null) {
            if (!validWalkthrough(r.walkthrough))
                return result(failure(s));
            preflight(r.walkthrough);
            if (s.assignment_id)
                return result(step(back(s)), ['PREFETCH_DIAGRAMS']);
            return result({ ...step(s), walkthrough: structuredClone(r.walkthrough), walkthroughReceivedAt: now, assignment_id: null, assignedAt: 0 }, ['PREFETCH_DIAGRAMS']);
        }
        if (r.outcome === 'logged')
            return result({ ...s, screen: 'LOGGED', response: null });
        if (r.outcome !== 'answered' || !r.glance?.trim())
            return result(failure(s));
        // The relay leaves body empty when the glance says it all; details then repeat the glance.
        const detail = r.body?.trim() ? r.body : r.glance;
        return result({ ...s, screen: 'ANSWER_GLANCE', response: r, pages: paginate(sanitizeForG2(detail), answerGraphic(r) ? ILLUSTRATED_PAGE_CHARS : BODY_PAGE_CHARS), page: 0 });
    }
    catch {
        return result(failure(s));
    }
}
export function transition(s: LensState, a: Action): Transition {
    if (a.type === 'PAIRED') {
        // Device credentials belong to settings.ts. Never copy the token into LensState.
        const pairing = { pair_code: a.pairing.pair_code, claimed: a.pairing.claimed, worker_name: a.pairing.worker_name };
        const next = { ...s, pairing };
        if (s.screen === 'PAIRING' && pairing.claimed)
            return result({ ...next, screen: taskDestination(s) }, ['POLL_ASSIGNMENT', 'PREFETCH_DIAGRAMS']);
        if (s.privacySeen && s.calibrated && !pairing.claimed && ['IDLE', 'STEP'].includes(s.screen))
            return result({ ...next, screen: 'PAIRING' });
        return result(next);
    }
    if (a.type === 'CALIBRATION_PROGRESS')
        return s.screen === 'CALIBRATE' ? result({ ...s, calibrationDone: a.done, calibrationNeeded: a.needed }) : result(s);
    if (a.type === 'CALIBRATED') {
        if (s.screen !== 'CALIBRATE')
            return result(s);
        if (!a.ok)
            return result({ ...s, notice: 'Calibration unavailable. Tap to continue.' });
        return result({ ...s, calibrated: true, screen: s.pairing?.claimed ? taskDestination(s) : 'PAIRING' }, ['POLL_ASSIGNMENT', 'PREFETCH_DIAGRAMS']);
    }
    if (a.type === 'ASSIGNMENT') {
        if (s.screen !== 'IDLE' || s.assignment_id)
            return result(s);
        const w = a.assignment.walkthrough, assignedAt = Date.parse(a.assignment.assigned_at), age = (a.now ?? assignedAt) - assignedAt;
        if (!a.assignment.assignment_id || !validWalkthrough(w) || !Number.isFinite(assignedAt) || age < 0 || age >= ASSIGNMENT_TTL_MS)
            return result(s);
        try {
            preflight(w);
        }
        catch {
            return result(s);
        }
        return result({ ...s, screen: 'TASK_READY', walkthrough: structuredClone(w), assignment_id: a.assignment.assignment_id, assignedAt, taskPaused: false, taskStarted: false, response: null });
    }
    if (a.type === 'DIAGRAM_READY')
        return s.screen === 'DIAGRAM' && s.diagramId === a.id ? result({ ...s, diagramReady: true }) : result(s);
    if (a.type === 'DIAGRAM_FAILED')
        return s.screen === 'DIAGRAM' && s.diagramId === a.id ? result({ ...step(s), notice: 'Diagram unavailable' }) : result(s);
    if (a.type === 'EMPTY_CAPTURE')
        return ['LISTENING', 'THINKING'].includes(s.screen) ? result(back(s)) : result(s);
    if (a.type === 'RESPONSE')
        return s.screen === 'THINKING' ? receive(s, a.response, a.now) : result(s);
    if (a.type === 'FAIL')
        return result(failure(s), ['CANCEL']);
    if (a.type === 'TEXT_ASK') {
        if (TEXT_ASK_BLOCKED.includes(s.screen))
            return result(s);
        // From LISTENING the open mic is cancelled and its return point kept; elsewhere the
        // answer returns to the screen the question was typed over.
        const from = s.screen === 'LISTENING' ? s : { ...s, returnTo: s.screen, returnState: s };
        return result({ ...from, screen: 'THINKING', response: null, notice: '' }, ['CANCEL', 'SEND_TEXT']);
    }
    // Press-and-hold talks exactly like a nod, so speech never depends on the IMU alone.
    if (a.type === 'LONG_PRESS')
        return transition(s, { type: 'NOD' });
    if (a.type === 'TIMEOUT' || a.type === 'DISMISS') {
        if (a.type === 'TIMEOUT' && timeoutFor(s) === null)
            return result(s);
        return result(s.screen === 'TASK_DONE' ? idle(s) : back(s), ['CANCEL']);
    }
    if (a.type === 'ENDPOINT')
        return s.screen === 'LISTENING' ? result({ ...s, screen: 'THINKING' }, ['STOP_AND_SEND']) : result(s);
    if (a.type === 'SHAKE') {
        if (['STEP', 'WALKTHROUGH', 'TASK_READY', 'THINKING', 'IDLE', 'PRIVACY', 'CALIBRATE', 'PAIRING'].includes(s.screen))
            return result(s);
        if (s.screen === 'DIAGRAM' || s.screen === 'STEP_DETAILS')
            return result(step(s));
        return result(back(s), ['CANCEL']);
    }
    if (a.type === 'NOD') {
        if (['LISTENING', 'THINKING', 'PRIVACY', 'CALIBRATE', 'PAIRING'].includes(s.screen))
            return result(s);
        if (s.screen !== 'TASK_READY')
            return listen(s);
    }
    if (a.type === 'DOUBLE_PRESS') {
        // A paused task resumes on a double tap: resuming must not depend on the IMU or voice.
        if (s.screen === 'IDLE' && s.assignment_id && s.walkthrough)
            return command(s, 'resume');
        if (['IDLE', 'PRIVACY', 'CALIBRATE', 'PAIRING'].includes(s.screen))
            return result(s, ['EXIT']);
        if (s.screen === 'STEP' || s.screen === 'WALKTHROUGH')
            return command(s, 'pause');
        if (s.screen === 'TASK_READY')
            return result({ ...s, screen: 'IDLE', taskPaused: true });
        if (s.screen === 'STEP_DETAILS' || s.screen === 'DIAGRAM')
            return result(step(s));
        if (s.screen === 'ANSWER_EXPANDED')
            return result({ ...s, screen: 'ANSWER_GLANCE', page: 0 });
        return result(back(s), ['CANCEL']);
    }
    if (a.type === 'UP' || a.type === 'DOWN') {
        const delta = a.type === 'UP' ? -1 : 1;
        if (s.screen === 'STEP_DETAILS' || s.screen === 'ANSWER_EXPANDED')
            return result({ ...s, page: Math.max(0, Math.min(s.pages.length - 1, s.page + delta)) });
        if (s.screen === 'STEP' || s.screen === 'WALKTHROUGH')
            return command(s, a.type === 'UP' ? 'back' : s.walkthrough?.steps[s.walkthrough.index].diagram ? 'diagram' : 'next');
        return result(s);
    }
    switch (s.screen) {
        case 'PRIVACY': return result({ ...s, privacySeen: true, screen: 'CALIBRATE' }, ['CALIBRATE']);
        case 'CALIBRATE': return result({ ...s, calibrated: true, screen: s.pairing?.claimed ? taskDestination(s) : 'PAIRING' }, ['POLL_ASSIGNMENT']);
        case 'PAIRING': return result(s);
        case 'TASK_READY': {
            const current = s.walkthrough?.steps[s.walkthrough.index];
            return current ? result({ ...step(s), taskStarted: true }, [...progress(s, 'task_started', null), ...progress(s, 'step_started', current.step_id), 'PREFETCH_DIAGRAMS']) : result(failure(s));
        }
        case 'STEP':
        case 'WALKTHROUGH': return command(s, 'details');
        case 'STEP_DETAILS': return s.page + 1 < s.pages.length ? result({ ...s, page: s.page + 1 }) : result(step(s));
        case 'DIAGRAM': return result(step(s));
        case 'TASK_DONE': return result(idle(s), ['POLL_ASSIGNMENT']);
        case 'IDLE':
        case 'NOT_FOUND':
        case 'CLARIFY':
        case 'ERROR': return listen(s);
        case 'LISTENING': return result({ ...s, screen: 'THINKING' }, ['STOP_AND_SEND']);
        case 'THINKING': return result(s);
        case 'ANSWER_GLANCE': return result({ ...s, screen: 'ANSWER_EXPANDED', page: 0, detailReturn: 'ANSWER_GLANCE' });
        case 'ANSWER_EXPANDED': return result({ ...s, screen: 'ANSWER_GLANCE', page: 0 });
        case 'LOGGED': return result(back(s));
    }
}
export function serializeSession(s: LensState): string {
    return JSON.stringify({ version: 2, session_id: s.session_id, privacySeen: s.privacySeen, micSource: s.micSource,
        calibrated: s.calibrated, walkthrough: s.screen === 'TASK_DONE' ? null : s.walkthrough, walkthroughReceivedAt: s.walkthroughReceivedAt,
        assignment_id: s.screen === 'TASK_DONE' ? null : s.assignment_id, assignedAt: s.assignedAt, taskPaused: s.taskPaused, taskStarted: s.taskStarted });
}
export function restoreSession(raw: string, now: number, newSessionId: string): LensState {
    const fresh = initialState(newSessionId);
    try {
        const saved = JSON.parse(raw);
        if (!saved || ![1, 2].includes(saved.version))
            return fresh;
        const s = { ...fresh, session_id: typeof saved.session_id === 'string' && saved.session_id ? saved.session_id : newSessionId,
            privacySeen: saved.privacySeen === true, calibrated: saved.calibrated === true, micSource: saved.micSource === 'phone' ? 'phone' as const : 'glasses' as const };
        s.screen = s.privacySeen ? 'IDLE' : 'PRIVACY';
        const assigned = typeof saved.assignment_id === 'string' && !!saved.assignment_id;
        const timestamp = assigned ? saved.assignedAt : saved.walkthroughReceivedAt, age = now - timestamp;
        if (s.privacySeen && typeof timestamp === 'number' && age >= 0 && age < (assigned ? ASSIGNMENT_TTL_MS : WALKTHROUGH_TTL_MS) && validWalkthrough(saved.walkthrough)) {
            try {
                preflight(saved.walkthrough);
            }
            catch {
                return s;
            }
            return { ...s, screen: assigned && saved.taskStarted === false ? 'TASK_READY' : 'STEP', walkthrough: saved.walkthrough, walkthroughReceivedAt: saved.walkthroughReceivedAt ?? 0,
                assignment_id: assigned ? saved.assignment_id : null, assignedAt: assigned ? timestamp : 0, taskPaused: false, taskStarted: assigned ? saved.taskStarted !== false : false };
        }
        return s;
    }
    catch {
        return fresh;
    }
}
export function timeoutFor(s: LensState): number | null {
    if (['PRIVACY', 'CALIBRATE', 'PAIRING', 'IDLE', 'TASK_READY', 'STEP', 'WALKTHROUGH', 'STEP_DETAILS', 'DIAGRAM'].includes(s.screen))
        return null;
    if (['ANSWER_GLANCE', 'ANSWER_EXPANDED', 'NOT_FOUND', 'CLARIFY', 'ERROR', 'LOGGED'].includes(s.screen) && isStep(s.returnTo))
        return GLANCE_TIMEOUT_MS;
    return s.screen === 'ANSWER_GLANCE' || s.screen === 'CLARIFY' ? GLANCE_TIMEOUT_MS : INACTIVITY_TIMEOUT_MS;
}
export interface LensPorts {
    startCapture(onLevel: (level: number) => void, onEndpoint?: (reason: 'speech_end' | 'no_speech' | 'cap') => void): Promise<void>;
    stopCapture(): Promise<{
        data_b64: string;
        sample_rate: 16000;
    }>;
    ask(request: AskRequest, opts?: {
        signal?: AbortSignal;
    }): Promise<AskResponse>;
    render(state: LensState, level: number, diagram?: DiagramImage): Promise<void>;
    persist(state: LensState): Promise<void>;
    exit(): Promise<void>;
    now(): number;
    onError(error: unknown): void;
    reportProgress?(event: ProgressEvent): void;
    getDiagram?(id: string): Promise<DiagramImage>;
    pollAssignment?(): void;
    calibrate?(onProgress: (done: number, needed: number) => void): Promise<{
        ok: boolean;
    }>;
}
/** Coordinates asynchronous effects independently of Part 2 and the SDK. */
export class LensController {
    state: LensState;
    private epoch = 0;
    private request: AbortController | null = null;
    private capture: Promise<void> = Promise.resolve();
    private timer: ReturnType<typeof setTimeout> | undefined;
    private deadline = 0;
    private disposed = false;
    private suspended = false;
    private level = 0;
    private diagrams = new Map<string, DiagramImage>();
    private diagramFetches = new Map<string, Promise<void>>();
    private progressTs = 0;
    private pendingText: { text: string; context: AskContext } | null = null;
    constructor(state: LensState, private readonly ports: LensPorts) { this.state = state; }
    /** Ask a typed question (from the phone screen). False when one is already in flight
     * or the lens is on a screen that refuses it (privacy, calibration). */
    askText(text: string, context?: AskContext): boolean {
        const question = text.trim();
        if (this.disposed || !question || TEXT_ASK_BLOCKED.includes(this.state.screen))
            return false;
        // No explicit context from the phone: ask about the step the worker is on.
        const w = this.state.walkthrough;
        const current: AskContext = { doc_id: w?.doc_id ?? null, step_id: w?.steps[w.index]?.step_id ?? null,
            ...(this.state.assignment_id ? { assignment_id: this.state.assignment_id } : {}) };
        this.pendingText = { text: question, context: context?.doc_id ? context : current };
        this.dispatch({ type: 'TEXT_ASK' });
        return true;
    }
    async start(): Promise<void> {
        await this.draw();
        this.armTimer();
        if (this.state.walkthrough)
            this.prefetch();
        if (this.state.screen === 'CALIBRATE')
            this.effect('CALIBRATE');
    }
    private draw(): Promise<void> {
        return this.ports.render(this.state, this.level, this.state.diagramId ? this.diagrams.get(this.state.diagramId) : undefined);
    }
    dispatch(action: Action): void {
        if (this.disposed)
            return;
        const { state, effects } = transition(this.state, action);
        if (state !== this.state) {
            this.state = state;
            this.level = 0;
            void this.draw().catch(this.ports.onError);
            void this.ports.persist(state).catch(this.ports.onError);
            this.armTimer();
        }
        for (const effect of effects)
            this.effect(effect);
    }
    private armTimer(): void {
        clearTimeout(this.timer);
        const ms = timeoutFor(this.state);
        this.deadline = ms === null ? 0 : this.ports.now() + ms;
        if (ms !== null && !this.suspended)
            this.timer = setTimeout(() => this.dispatch({ type: 'TIMEOUT' }), ms);
    }
    private effect(effect: Effect): void {
        if (typeof effect === 'object') {
            if (effect.type === 'REPORT_PROGRESS' && this.state.assignment_id) {
                this.progressTs = Math.max(this.ports.now(), this.progressTs + 1);
                try {
                    this.ports.reportProgress?.({ assignment_id: this.state.assignment_id, step_id: effect.step_id, kind: effect.kind, ts: this.progressTs });
                }
                catch (error) {
                    this.ports.onError(error);
                }
            }
            if (effect.type === 'SHOW_DIAGRAM')
                void this.fetchDiagram(effect.diagram_id);
            return;
        }
        if (effect === 'PREFETCH_DIAGRAMS') {
            this.prefetch();
            return;
        }
        if (effect === 'POLL_ASSIGNMENT') {
            this.ports.pollAssignment?.();
            return;
        }
        if (effect === 'CALIBRATE') {
            void this.ports.calibrate?.((done, needed) => this.dispatch({ type: 'CALIBRATION_PROGRESS', done, needed }))
                .then(value => this.dispatch({ type: 'CALIBRATED', ok: value.ok }))
                .catch(error => { this.ports.onError(error); this.dispatch({ type: 'CALIBRATED', ok: false }); });
            return;
        }
        if (effect === 'EXIT') {
            // Keep handlers active if the user cancels native exit confirmation.
            void this.ports.persist(this.state).then(() => this.ports.exit()).catch(this.ports.onError);
            return;
        }
        if (effect === 'CANCEL') {
            this.epoch += 1;
            this.request?.abort();
            this.request = null;
            this.capture = this.capture.then(async () => { await this.ports.stopCapture(); }).catch(this.ports.onError);
            return;
        }
        if (effect === 'SEND_TEXT') {
            const pending = this.pendingText;
            this.pendingText = null;
            if (!pending)
                return;
            const epoch = this.epoch;
            const request = new AbortController();
            this.request = request;
            const req: AskRequest = { session_id: this.state.session_id, text: pending.text,
                revision: this.state.walkthrough?.revision ?? null, context: pending.context };
            // Queued behind the cancelled capture so the mic is closed before the ask goes out.
            this.capture = this.capture.then(() => {
                if (epoch !== this.epoch || this.disposed)
                    return;
                void this.ports.ask(req, { signal: request.signal }).then(response => {
                    if (epoch === this.epoch && !this.disposed && !request.signal.aborted)
                        this.dispatch({ type: 'RESPONSE', response, now: this.ports.now() });
                }).catch(error => {
                    if (epoch === this.epoch && !this.disposed && !request.signal.aborted) {
                        this.ports.onError(error);
                        this.dispatch({ type: 'FAIL' });
                    }
                });
            });
            return;
        }
        if (effect === 'START_CAPTURE') {
            const epoch = ++this.epoch;
            this.request?.abort();
            this.capture = this.capture.then(() => {
                if (this.epoch !== epoch || this.disposed)
                    return;
                return this.ports.startCapture(level => {
                    if (this.epoch !== epoch || this.state.screen !== 'LISTENING' || this.suspended)
                        return;
                    this.level = level;
                    void this.draw().catch(this.ports.onError);
                }, () => {
                    if (epoch === this.epoch && !this.disposed && this.state.screen === 'LISTENING')
                        this.dispatch({ type: 'ENDPOINT' });
                });
            }).catch(error => {
                this.ports.onError(error);
                if (epoch === this.epoch && !this.disposed)
                    this.dispatch({ type: 'FAIL' });
            });
            return;
        }
        const epoch = this.epoch;
        const state = this.state;
        const request = new AbortController();
        this.request = request;
        this.capture = this.capture.then(async () => {
            if (epoch !== this.epoch || this.disposed)
                return;
            const audio = await this.ports.stopCapture();
            if (epoch !== this.epoch || this.disposed)
                return;
            if (!audio.data_b64) {
                this.dispatch({ type: 'EMPTY_CAPTURE' });
                return;
            }
            const w = state.walkthrough;
            const req: AskRequest = { session_id: state.session_id, audio: { format: 'pcm_s16le', channels: 1, ...audio },
                revision: w?.revision ?? null, context: { doc_id: w?.doc_id ?? null, step_id: w?.steps[w.index]?.step_id ?? null,
                    ...(state.assignment_id ? { assignment_id: state.assignment_id } : {}) } };
            // Don't hold the capture queue while waiting on the relay. Cancel must
            // stop audio even if the relay ignores AbortSignal.
            void this.ports.ask(req, { signal: request.signal }).then(response => {
                if (epoch === this.epoch && !this.disposed && !request.signal.aborted)
                    this.dispatch({ type: 'RESPONSE', response, now: this.ports.now() });
            }).catch(error => {
                if (epoch === this.epoch && !this.disposed && !request.signal.aborted) {
                    this.ports.onError(error);
                    this.dispatch({ type: 'FAIL' });
                }
            });
        }).catch(error => {
            this.ports.onError(error);
            if (epoch === this.epoch && !this.disposed)
                this.dispatch({ type: 'FAIL' });
        });
    }
    private prefetch(): void {
        const w = this.state.walkthrough;
        for (const current of w?.steps.slice(w.index, w.index + 2) ?? [])
            if (current.diagram)
                void this.fetchDiagram(current.diagram.diagram_id);
    }
    private fetchDiagram(id: string): Promise<void> {
        if (this.diagrams.has(id)) {
            this.dispatch({ type: 'DIAGRAM_READY', id });
            return Promise.resolve();
        }
        if (this.diagramFetches.has(id))
            return this.diagramFetches.get(id)!;
        const fetch = (async () => {
            try {
                if (!this.ports.getDiagram)
                    throw new Error('Diagram client unavailable');
                const image = await this.ports.getDiagram(id);
                if (image.diagram_id !== id || image.tiles.length !== 2 || new Set(image.tiles.map(t => t.slot)).size !== 2 ||
                    image.tiles.some(t => ![0, 1].includes(t.slot) || t.width !== 288 || t.height !== 144 || !t.image))
                    throw new Error('Invalid diagram tiles');
                if (this.disposed)
                    return;
                if (this.diagrams.size >= 8)
                    this.diagrams.delete(this.diagrams.keys().next().value!);
                this.diagrams.set(id, image);
                this.dispatch({ type: 'DIAGRAM_READY', id });
            }
            catch (error) {
                this.ports.onError(error);
                this.dispatch({ type: 'DIAGRAM_FAILED', id });
            }
            finally {
                this.diagramFetches.delete(id);
            }
        })();
        this.diagramFetches.set(id, fetch);
        return fetch;
    }
    async suspend(): Promise<void> {
        this.suspended = true;
        clearTimeout(this.timer);
        if (this.state.screen === 'LISTENING' || this.state.screen === 'THINKING')
            this.dispatch({ type: 'DISMISS' });
        await this.ports.persist(this.state);
    }
    async resume(): Promise<void> {
        if (this.disposed)
            return;
        this.suspended = false;
        if (this.deadline && this.ports.now() >= this.deadline)
            this.dispatch({ type: 'TIMEOUT' });
        else if (this.deadline) {
            clearTimeout(this.timer);
            this.timer = setTimeout(() => this.dispatch({ type: 'TIMEOUT' }), this.deadline - this.ports.now());
        }
        await this.draw();
    }
    async dispose(): Promise<void> {
        this.disposed = true;
        clearTimeout(this.timer);
        this.epoch += 1;
        this.request?.abort();
        await this.capture;
        await this.ports.stopCapture();
        await this.ports.persist(this.state);
    }
}
