// @vitest-environment jsdom
// v3 worker loop on the lens and phone (README-V3-PART-1-LENS-UX.md §4): clarify, scoped
// walkthroughs, the picture command, chained questions. Fixtures quote corpus/SOP-230-C.md.
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { initialState, restoreSession, serializeSession, timeoutFor, transition, type LensState } from '../src/state';
import { renderScreen } from '../src/ui/screens';
import { UI_FIXTURES } from '../src/ui/fixtures';
import { AnswerDetail } from '../src/phone/components/AnswerDetail';
import type { AskResponse, Command } from '../src/types';

const { fixtures, mockAsk, setMockDelayMs, resetMockV2 } = await import('../src/mock/index.ts');
const { CLARIFY_PUMPS, CAPPUCCINO, pumpsFor } = fixtures;
afterEach(cleanup);

const idle = (): LensState => ({ ...initialState('v3'), screen: 'IDLE', privacySeen: true, calibrated: true,
  pairing: { pair_code: '4F7K', claimed: true, worker_name: 'Fixture' } });
/** Double nod, speech, endpoint, relay response: what the lens does for every spoken ask. */
function ask(s: LensState, response: AskResponse): LensState {
  const listening = transition(s, { type: 'NOD' }).state;
  expect(listening.screen).toBe('LISTENING');
  return transition(transition(listening, { type: 'ENDPOINT' }).state, { type: 'RESPONSE', response: structuredClone(response), now: 2000 }).state;
}
const command = (name: Command): AskResponse => ({ ...UI_FIXTURES.answer, outcome: 'command', intent: 'command', command: name, verified: false });
const text = (s: LensState) => renderScreen(s, 0);
const opened = () => ask(idle(), CAPPUCCINO); // SOP-230 steps 2.2-4.4, scoped to cappuccino 3.2-3.4

describe('scoped walkthroughs', () => {
  it('opens at the scope start and counts inside the scope', () => {
    const s = opened();
    expect(s.screen).toBe('STEP'); expect(s.walkthrough!.index).toBe(4);
    expect(text(s).header).toMatch(/^1\/3 /); expect(text(s).main).toContain('Cappuccino: pull espresso');
  });
  it('back floors at the scope start; next on the last scoped step finishes the task', () => {
    let s = opened();
    s = transition(s, { type: 'UP' }).state; expect(s.walkthrough!.index).toBe(4);
    s = ask(s, command('back')); expect(s.walkthrough!.index).toBe(4);
    s = ask(s, command('next')); expect(text(s).header).toMatch(/^2\/3 /);
    s = transition(s, { type: 'DOWN' }).state; expect(text(s).header).toMatch(/^3\/3 /);
    s = ask(s, command('next'));
    expect(s.screen).toBe('TASK_DONE'); expect(text(s).main).toBe('3/3 steps');
  });
  it('refuses an impossible scope', () => {
    for (const scope of [{ start: 4, end: 11 }, { start: 5, end: 7 }, { start: 4, end: 4 }, { start: 1.5, end: 7 }]) {
      const bad = structuredClone(CAPPUCCINO); bad.walkthrough!.scope = scope;
      expect(ask(idle(), bad).screen).toBe('ERROR');
    }
  });
  it('a restored session keeps its scope', () => {
    const s = transition(opened(), { type: 'DOWN' }).state;
    const back = restoreSession(serializeSession(s), 3000, 'new');
    expect(back.screen).toBe('STEP'); expect(back.walkthrough!.scope).toEqual({ start: 4, end: 7 });
    expect(text(back).header).toMatch(/^2\/3 /);
  });
});

describe('clarify', () => {
  it('an ambiguous question asks which one, from the relay\'s options', () => {
    const c = ask(opened(), CLARIFY_PUMPS);
    expect(c.screen).toBe('CLARIFY');
    expect(text(c)).toEqual({ header: 'Which size?', main: 'Small\nMedium\nLarge', footer: 'nod twice: answer' });
    expect(timeoutFor(c)).toBe(20000);
  });
  it('the reply\'s answer returns to the step the question was asked on', () => {
    const c = ask(transition(opened(), { type: 'DOWN' }).state, CLARIFY_PUMPS);
    const a = ask(c, pumpsFor('medium'));
    expect(a.screen).toBe('ANSWER_GLANCE'); expect(text(a).main).toBe('3 pumps in Medium'); expect(text(a).graphic_id).toBe('recipe-pumps');
    for (const leave of ['DISMISS', 'TIMEOUT', 'SHAKE'] as const) {
      const s = transition(a, { type: leave }).state;
      expect(s.screen).toBe('STEP'); expect(s.walkthrough!.index).toBe(5);
    }
  });
  it('cancel goes back to the step; silence keeps the question open', () => {
    const c = ask(opened(), CLARIFY_PUMPS);
    for (const leave of ['SHAKE', 'TIMEOUT', 'DOUBLE_PRESS'] as const) expect(transition(c, { type: leave }).state.screen).toBe('STEP');
    const silent = transition(transition(c, { type: 'NOD' }).state, { type: 'EMPTY_CAPTURE' }).state;
    expect(silent.screen).toBe('CLARIFY');
  });
  it('a typed reply (phone chip) resolves the same way', () => {
    const c = ask(opened(), CLARIFY_PUMPS);
    const thinking = transition(c, { type: 'TEXT_ASK' });
    expect(thinking.state.screen).toBe('THINKING'); expect(thinking.effects).toEqual(['CANCEL', 'SEND_TEXT']);
    const a = transition(thinking.state, { type: 'RESPONSE', response: pumpsFor('small'), now: 3000 }).state;
    expect(transition(a, { type: 'DISMISS' }).state.screen).toBe('STEP');
  });
  it('anything short of a valid clarify is a plain not found', () => {
    const bad: AskResponse[] = [
      { ...CLARIFY_PUMPS, needs_clarification: false },
      { ...CLARIFY_PUMPS, clarify: null },
      { ...CLARIFY_PUMPS, clarify: { prompt: 'Which size?', options: ['Small'] } },
      { ...CLARIFY_PUMPS, clarify: { prompt: 'Which size?', options: ['Small', 'Medium', 'Large', 'Kids'] } },
      { ...CLARIFY_PUMPS, clarify: { prompt: 'Which size?', options: ['Small', 'x'.repeat(25)] } },
      { ...CLARIFY_PUMPS, clarify: { prompt: 'x'.repeat(41), options: ['Small', 'Medium'] } },
    ];
    for (const r of bad) { const s = ask(opened(), r); expect(s.screen).toBe('NOT_FOUND'); expect(s.response).toBeNull(); }
  });
});

describe('chained questions', () => {
  it('a question asked from an answer still returns to the step', () => {
    let s = transition(opened(), { type: 'DOWN' }).state;
    s = ask(s, UI_FIXTURES.answer); expect(s.screen).toBe('ANSWER_GLANCE');
    s = ask(s, UI_FIXTURES.not_found); expect(s.screen).toBe('NOT_FOUND');
    s = ask(s, UI_FIXTURES.answer);
    s = transition(s, { type: 'DISMISS' }).state;
    expect(s.screen).toBe('STEP'); expect(s.walkthrough!.index).toBe(5);
  });
});

describe('show me the picture', () => {
  it('with a reference picture and no relay diagram, opens the details beside the picture', () => {
    const s = ask(opened(), command('diagram'));
    expect(s.screen).toBe('STEP_DETAILS'); expect(text(s).graphic_id).toBe('recipe-cup');
  });
  it('with neither, says so and stays on the step', () => {
    const last = transition(transition(opened(), { type: 'DOWN' }).state, { type: 'DOWN' }).state; // 3.4 has no reference
    const s = ask(last, command('diagram'));
    expect(s.screen).toBe('STEP'); expect(s.notice).toBe('No diagram for this step');
  });
  it('marks a picture the step screen had no room for', () => {
    const s = opened();
    s.walkthrough!.steps[4].warning = 'Hold the cup by the base and keep fingers clear of the spouts.';
    s.walkthrough!.steps[4].checkpoint = 'Shots land in the cup, not the drip tray.';
    expect(text(s).graphic_id).toBeUndefined(); expect(text(s).footer).toContain('[picture]');
  });
});

describe('mock relay', () => {
  it('resolves a clarify reply once, like the relay session', async () => {
    setMockDelayMs(0); resetMockV2();
    const q = await mockAsk({ session_id: 's', text: 'How many pumps of syrup?' });
    expect(q.clarify?.options).toEqual(['Small', 'Medium', 'Large']);
    expect((await mockAsk({ session_id: 's', text: 'medium please' })).glance).toBe('3 pumps in Medium');
    expect((await mockAsk({ session_id: 's', text: 'medium' })).outcome).toBe('not_found');
  });
});

describe('phone', () => {
  it('shows the clarify options as chips that send the reply', () => {
    const sent: string[] = [];
    render(<AnswerDetail res={CLARIFY_PUMPS} pinnedStepId={null} onUseStep={() => {}} onAsk={(t) => sent.push(t)} />);
    expect(screen.getByText('Which size?')).toBeTruthy();
    expect(screen.queryByText('Not in your SOPs. Ask your manager to add it.')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Medium' }));
    expect(sent).toEqual(['Medium']);
  });
  it('disables the chips while an ask is in flight', () => {
    render(<AnswerDetail res={CLARIFY_PUMPS} pinnedStepId={null} onUseStep={() => {}} />);
    expect((screen.getByRole('button', { name: 'Small' }) as HTMLButtonElement).disabled).toBe(true);
  });
  it('shows only the scoped steps, with the whole procedure one tap away', () => {
    render(<AnswerDetail res={CAPPUCCINO} pinnedStepId={null} onUseStep={() => {}} />);
    expect(screen.getByText(/^Step 1/).textContent).toBe('Step 1 of 3');
    fireEvent.click(screen.getByRole('button', { name: 'Show whole procedure (10 steps)' }));
    expect(screen.getByText(/^Step 5/).textContent).toBe('Step 5 of 10');
  });
});
