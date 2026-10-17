import type { LensState } from '../state';
import { sanitizeForG2 } from './glyphs';
import { paginate } from './paginate';

export interface ScreenText { header: string; main: string; footer: string; }
const short = (text: string, cap: number) => paginate(sanitizeForG2(text), cap)[0];
const safe = (text: ScreenText): ScreenText => ({ header: sanitizeForG2(text.header),
  main: sanitizeForG2(text.main), footer: sanitizeForG2(text.footer) });
const pressToAsk = 'press: ask   double: exit';

export function privacyScreen(): ScreenText {
  return { header: 'PRIVACY', main: 'Audio is processed to answer, not stored. Ask before recording others.', footer: 'press: continue   double: exit' };
}
export function idleScreen(): ScreenText { return { header: '', main: '', footer: pressToAsk }; }
export function listeningScreen(level = 0): ScreenText {
  const bars = '▁▂▃▄▅▆▇█';
  const index = Math.round(Math.max(0, Math.min(1, Number.isFinite(level) ? level : 0)) * 7);
  return { header: 'LISTENING', main: bars[index].repeat(10), footer: 'press: send   double: cancel' };
}
export function thinkingScreen(): ScreenText { return { header: '...', main: 'checking SOPs', footer: 'double: cancel' }; }
export function notFoundScreen(): ScreenText { return { header: 'NOT FOUND', main: 'Not in approved SOPs\nTry rephrasing or ask your supervisor.', footer: 'press: ask again   double: dismiss' }; }
export function errorScreen(): ScreenText { return { header: 'ERROR', main: 'Something went wrong\nNo verified answer is available.', footer: 'press: retry   double: dismiss' }; }
export function loggedScreen(): ScreenText { return { header: 'LOGGED', main: 'Deviation logged.', footer: 'press: done   double: dismiss' }; }
export function glanceScreen(state: LensState): ScreenText {
  if (state.response?.verified !== true) return errorScreen();
  return { header: '', main: short(state.response.glance, 60), footer: `${short(state.response.source, 46)}  [+]` };
}
export function expandedScreen(state: LensState): ScreenText {
  if (state.response !== null && state.response.verified !== true) return errorScreen();
  // Restored walkthroughs have no ordinary response; their validated stored steps are the source.
  if (state.detailReturn !== 'WALKTHROUGH' && state.response?.verified !== true) return errorScreen();
  if (state.detailReturn === 'WALKTHROUGH' && !state.walkthrough) return errorScreen();
  const source = state.detailReturn === 'WALKTHROUGH' ? `${state.walkthrough!.doc_id} rev ${state.walkthrough!.revision}` : state.response!.source;
  return { header: `DETAILS ${state.page + 1}/${state.pages.length}`,
    main: state.pages[state.page] ?? '', footer: `${short(source, 32)}  swipe: page  press: back` };
}
export function walkthroughScreen(state: LensState): ScreenText {
  const w = state.walkthrough;
  if (!w || (state.response !== null && state.response.verified !== true)) return errorScreen();
  const step = w.steps[w.index];
  const progress = Math.max(1, Math.round(((w.index + 1) / w.total) * 10));
  return { header: `${short(`${w.doc_id} rev ${w.revision}`, 30)}  step ${w.index + 1}/${w.total}`,
    main: `${'━'.repeat(progress)}${'─'.repeat(10 - progress)}\n${short(step.glance, 130)}`,
    footer: 'swipe: step   press: details' };
}
export function renderScreen(state: LensState, level = 0): ScreenText {
  try {
    switch (state.screen) {
      case 'PRIVACY': return safe(privacyScreen());
      case 'IDLE': return safe(idleScreen());
      case 'LISTENING': return safe(listeningScreen(level));
      case 'THINKING': return safe(thinkingScreen());
      case 'ANSWER_GLANCE': return safe(glanceScreen(state));
      case 'ANSWER_EXPANDED': return safe(expandedScreen(state));
      case 'NOT_FOUND': return safe(notFoundScreen());
      case 'WALKTHROUGH': return safe(walkthroughScreen(state));
      case 'LOGGED': return safe(loggedScreen());
      case 'ERROR': return safe(errorScreen());
    }
  } catch { return errorScreen(); }
}
