import type { LensState } from '../state';
import { sanitizeForG2 } from './glyphs';
import { paginate } from './paginate';

export interface ScreenText { header: string; main: string; footer: string; }
const short = (text: string, cap: number) => paginate(sanitizeForG2(text), cap)[0];
const safe = (text: ScreenText): ScreenText => ({ header: sanitizeForG2(text.header),
  main: sanitizeForG2(text.main), footer: sanitizeForG2(text.footer) });

export function privacyScreen(): ScreenText {
  return { header: 'PRIVACY', main: 'Audio is processed to answer, not stored. Ask before recording others.\nNod twice to talk. The mic closes when you stop speaking.', footer: 'press: continue   double: exit' };
}
export function idleScreen(): ScreenText { return { header: '', main: '', footer: 'nod twice: speak   double: exit' }; }
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
export function stepScreen(state: LensState): ScreenText {
  const w=state.walkthrough, current=w?.steps[w.index];
  if (!w || !current) return errorScreen();
  const progress=Math.max(1,Math.round((w.index+1)/w.total*10));
  return {header:`${short(`${w.doc_id} rev ${w.revision}`,22)}  ${w.index+1}/${w.total} ${'━'.repeat(progress)}${'─'.repeat(10-progress)}`,
    main:[short(current.glance,60),current.warning?`! ${short(current.warning,80)}`:'',current.checkpoint?`> ${short(current.checkpoint,60)}`:''].filter(Boolean).join('\n\n'),
    footer:state.notice || `nod: speak${current.diagram?'   [diagram]':''}`};
}
export function renderScreen(state: LensState, level = 0): ScreenText {
  try {
    switch (state.screen) {
      case 'PRIVACY': return safe(privacyScreen());
      case 'CALIBRATE': return safe({header:'CALIBRATE',main:`Nod twice now (${state.calibrationDone}/${state.calibrationNeeded})`,footer:state.notice || 'tap: use default gestures'});
      case 'PAIRING': return safe({header:'PAIRING',main:state.pairing?`Pair code ${short(state.pairing.pair_code,16)}\nEnter it in the Margin portal.`:'Getting pair code...',footer:'waiting for supervisor'});
      case 'TASK_READY': return safe({header:'TASK READY',main:`Task ready: ${short(state.walkthrough?.title ?? '',90)}\n${state.walkthrough?.total ?? 0} steps`,footer:'nod twice to start'});
      case 'STEP': return safe(stepScreen(state));
      case 'STEP_DETAILS': return safe({header:`STEP DETAILS ${state.page+1}/${state.pages.length}`,main:state.pages[state.page] ?? '',footer:'swipe: page   shake: back'});
      case 'DIAGRAM': return safe({header:`${short(state.walkthrough?.doc_id ?? '',24)}  diagram`,main:'',footer:state.diagramReady?`${short(state.walkthrough?.steps[state.walkthrough.index].diagram?.alt ?? '',45)}  shake: back`:'loading diagram'});
      case 'TASK_DONE': return safe({header:'TASK COMPLETE',main:`Task complete. ${state.walkthrough?.total ?? 0}/${state.walkthrough?.total ?? 0} steps`,footer:'nod: speak   tap: done'});
      case 'IDLE': return safe({...idleScreen(),footer:state.notice || (state.assignment_id?'nod: say resume   double: exit':idleScreen().footer)});
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
