import { answerGraphic, stepGraphic, ILLUSTRATED_PAGE_CHARS } from './sop-graphics';
import type { LensState } from '../state';
import { sanitizeForG2 } from './glyphs';
import { paginate } from './paginate';
export interface ScreenText {
    graphic_id?: string;
    header: string;
    main: string;
    footer: string;
}
/**
 * Lens copy is deliberately minimal: the value or action, never a sentence that
 * restates it. Gesture hints ("press: send") are the one thing a worker stops
 * needing, so they are separate from content and main.ts drops them once the
 * worker has used enough gestures (see settings.ts HINT_GESTURES).
 */
export interface RenderOptions {
    hints?: boolean;
}
const short = (text: string, cap: number) => paginate(sanitizeForG2(text), cap)[0];
const safe = (text: ScreenText): ScreenText => ({ header: sanitizeForG2(text.header),
    main: sanitizeForG2(text.main), footer: sanitizeForG2(text.footer),
    ...(text.graphic_id ? { graphic_id: text.graphic_id } : {}) });
const join = (...parts: string[]) => parts.filter(Boolean).join('  ');
/** "SOP-114 Sec 4.2 rev C" -> "SOP-114 4.2". The revision stays on the phone. */
export function compactSource(source: string): string {
    const m = /^(\S+) Sec (\S+)(?: rev \S+)?$/.exec(source.trim());
    return m ? `${m[1]} ${m[2]}` : source;
}
const bar = (index: number, total: number) => {
    const done = Math.max(1, Math.round(((index + 1) / Math.max(total, 1)) * 10));
    return `${'━'.repeat(done)}${'─'.repeat(10 - done)}`;
};
export function privacyScreen(o: RenderOptions = {}): ScreenText {
    return { header: 'PRIVACY', main: 'Audio not stored.\nAsk before recording others.\nNod twice or hold to talk.', footer: o.hints === false ? '' : 'press: ok   double: exit' };
}
export function idleScreen(o: RenderOptions = {}): ScreenText { return { header: '', main: '', footer: o.hints === false ? '' : 'nod twice: speak' }; }
export function listeningScreen(level = 0, o: RenderOptions = {}): ScreenText {
    const bars = '▁▂▃▄▅▆▇█';
    const index = Math.round(Math.max(0, Math.min(1, Number.isFinite(level) ? level : 0)) * 7);
    return { header: 'LISTENING', main: bars[index].repeat(10), footer: o.hints === false ? '' : 'press: send   double: cancel' };
}
export function thinkingScreen(): ScreenText { return { header: '', main: '...', footer: '' }; }
export function notFoundScreen(o: RenderOptions = {}): ScreenText { return { header: '', main: 'Not in approved SOPs', footer: o.hints === false ? '' : 'press: ask again' }; }
export function errorScreen(o: RenderOptions = {}): ScreenText { return { header: 'ERROR', main: 'No verified answer', footer: o.hints === false ? '' : 'press: retry' }; }
export function loggedScreen(): ScreenText { return { header: '', main: 'Deviation logged', footer: '' }; }
export function glanceScreen(state: LensState, o: RenderOptions = {}): ScreenText {
    if (state.response?.verified !== true)
        return errorScreen(o);
    return { graphic_id: answerGraphic(state.response)?.id, header: '', main: short(state.response.glance, 60), footer: `${short(compactSource(state.response.source), 32)}  [+]` };
}
export function expandedScreen(state: LensState, o: RenderOptions = {}): ScreenText {
    if (state.response !== null && state.response.verified !== true)
        return errorScreen(o);
    // Restored walkthroughs have no ordinary response; their validated stored steps are the source.
    if (state.detailReturn !== 'WALKTHROUGH' && state.response?.verified !== true)
        return errorScreen(o);
    if (state.detailReturn === 'WALKTHROUGH' && !state.walkthrough)
        return errorScreen(o);
    const source = state.detailReturn === 'WALKTHROUGH' ? state.walkthrough!.doc_id : compactSource(state.response!.source);
    const graphic = state.detailReturn === 'WALKTHROUGH' ? stepGraphic(state.walkthrough!.steps[state.walkthrough!.index]) : answerGraphic(state.response);
    return { graphic_id: graphic?.id, header: state.pages.length > 1 ? `${state.page + 1}/${state.pages.length}` : '',
        main: state.pages[state.page] ?? '', footer: join(short(source, 32), o.hints === false ? '' : 'swipe: page') };
}
export function walkthroughScreen(state: LensState, o: RenderOptions = {}): ScreenText {
    const w = state.walkthrough;
    if (!w || (state.response !== null && state.response.verified !== true))
        return errorScreen(o);
    const step = w.steps[w.index];
    return { graphic_id: stepGraphic(step)?.id, header: `${w.index + 1}/${w.total}  ${bar(w.index, w.total)}`,
        main: short(step.glance, 130),
        footer: o.hints === false ? '' : 'swipe: step   press: details' };
}
export function stepScreen(state: LensState, o: RenderOptions = {}): ScreenText {
    const w = state.walkthrough, current = w?.steps[w.index];
    if (!w || !current)
        return errorScreen(o);
    const copyLength = [current.glance, current.warning, current.checkpoint].filter(Boolean).join('\n\n! > ').length;
    return { graphic_id: copyLength <= ILLUSTRATED_PAGE_CHARS ? stepGraphic(current)?.id : undefined, header: `${w.index + 1}/${w.total}  ${bar(w.index, w.total)}`,
        main: [short(current.glance, 60), current.warning ? `! ${short(current.warning, 80)}` : '', current.checkpoint ? `> ${short(current.checkpoint, 60)}` : ''].filter(Boolean).join('\n\n'),
        footer: state.notice || join(o.hints === false ? '' : 'nod twice: speak', current.diagram ? '[diagram]' : '') };
}
export function renderScreen(state: LensState, level = 0, o: RenderOptions = {}): ScreenText {
    const hint = (text: string) => (o.hints === false ? '' : text);
    try {
        switch (state.screen) {
            case 'PRIVACY': return safe(privacyScreen(o));
            case 'CALIBRATE': return safe({ header: 'CALIBRATE', main: `Nod twice (${state.calibrationDone}/${state.calibrationNeeded})`, footer: state.notice || 'press: skip' });
            case 'PAIRING': return safe({ header: 'PAIR', main: state.pairing ? `${short(state.pairing.pair_code, 16)}\nEnter in Specs portal` : '...', footer: '' });
            case 'TASK_READY': return safe({ header: 'NEW TASK', main: `${short(state.walkthrough?.title ?? '', 90)}\n${state.walkthrough?.total ?? 0} steps`, footer: hint('nod twice: start') });
            case 'STEP': return safe(stepScreen(state, o));
            case 'STEP_DETAILS': return safe({ graphic_id: state.walkthrough ? stepGraphic(state.walkthrough.steps[state.walkthrough.index])?.id : undefined, header: state.pages.length > 1 ? `${state.page + 1}/${state.pages.length}` : '', main: state.pages[state.page] ?? '', footer: hint('swipe: page   double: back') });
            case 'DIAGRAM': return safe({ header: '', main: '', footer: state.diagramReady ? join(short(state.walkthrough?.steps[state.walkthrough.index].diagram?.alt ?? '', 45), hint('double: back')) : '...' });
            case 'TASK_DONE': return safe({ header: 'DONE', main: `${state.walkthrough?.total ?? 0}/${state.walkthrough?.total ?? 0} steps`, footer: hint('press: close') });
            case 'IDLE': return safe({ ...idleScreen(o), footer: state.notice || (state.assignment_id ? hint('nod twice: resume') : idleScreen(o).footer) });
            case 'LISTENING': return safe(listeningScreen(level, o));
            case 'THINKING': return safe(thinkingScreen());
            case 'ANSWER_GLANCE': return safe(glanceScreen(state, o));
            case 'ANSWER_EXPANDED': return safe(expandedScreen(state, o));
            case 'NOT_FOUND': return safe(notFoundScreen(o));
            case 'WALKTHROUGH': return safe(walkthroughScreen(state, o));
            case 'LOGGED': return safe(loggedScreen());
            case 'ERROR': return safe(errorScreen(o));
        }
    }
    catch {
        return errorScreen(o);
    }
}
