import { initialState, transition, type LensState, type Screen } from '../src/state';
import { UI_FIXTURES } from '../src/ui/fixtures';
export function stateFor(screen: Screen): LensState {
  const base = { ...initialState('session-test'), privacySeen: true, screen };
  if (screen === 'PRIVACY') return { ...base, privacySeen: false };
  if (screen === 'WALKTHROUGH') return transition({ ...base, screen: 'THINKING' }, { type: 'RESPONSE', response: structuredClone(UI_FIXTURES.walkthrough), now: 1000 }).state;
  if (screen === 'ANSWER_GLANCE' || screen === 'ANSWER_EXPANDED') return { ...transition({ ...base, screen: 'THINKING' }, { type: 'RESPONSE', response: structuredClone(UI_FIXTURES.answer), now: 1000 }).state, screen };
  return base;
}
