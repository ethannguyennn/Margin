// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { initialState, transition } from '../src/state';
import { renderScreen } from '../src/ui/screens';
import { parseDisplay } from '../src/ui/generated-display';
import { AnswerDetail } from '../src/phone/components/AnswerDetail';
import { UI_FIXTURES } from '../src/ui/fixtures';
import type { AskResponse, DisplaySpec } from '../src/types';

afterEach(cleanup);

function response(kind: DisplaySpec['kind']): AskResponse {
  return { ...structuredClone(UI_FIXTURES.answer), display: { kind, items: [
    'Disconnect power.', 'Torque all four M5 bracket screws to 4 N-m in a star pattern.',
  ] } };
}

function receive(res: AskResponse) {
  return transition({ ...initialState('display-test'), screen: 'THINKING' },
    { type: 'RESPONSE', response: res, now: 1000 }).state;
}

describe('Gemini selected SOP displays', () => {
  it.each(['checklist', 'warning'] as const)('opens the %s card on the lens and pages through every excerpt', kind => {
    let state = receive(response(kind));
    expect(state.screen).toBe('ANSWER_EXPANDED');
    let card = renderScreen(state);
    expect(card.header).toBe(`${kind.toUpperCase()} 1/2`);
    expect(card.main).toContain('Disconnect power.');
    expect(card.footer).toContain('SOP-114');
    state = transition(state, { type: 'DOWN' }).state;
    card = renderScreen(state);
    expect(card.header).toBe(`${kind.toUpperCase()} 2/2`);
    expect(card.main).toContain('4 N-m');
    expect(card.main.startsWith('□ ')).toBe(kind === 'checklist');
    state = transition(state, { type: 'DOWN' }).state;
    expect(renderScreen(state).header).toContain('DETAILS');
    state = transition(state, { type: 'PRESS' }).state;
    expect(state.screen).toBe('ANSWER_GLANCE');
    expect(renderScreen(state).header).toBe(kind.toUpperCase());
  });

  it('keeps maximum sized excerpts within the lens budget without dropping any text', () => {
    const res = response('checklist');
    res.display!.items = Array.from({ length: 4 }, (_, i) => `${i} ${'x'.repeat(178)}`);
    let state = receive(res);
    for (const item of res.display!.items) {
      const card = renderScreen(state);
      expect(card.main).toBe(`□ ${item}`);
      expect(Object.values(card).join('').length).toBeLessThanOrEqual(450);
      state = transition(state, { type: 'DOWN' }).state;
    }
  });

  it.each(['checklist', 'warning'] as const)('renders the %s card on the phone with citations', kind => {
    render(<AnswerDetail res={response(kind)} pinnedStepId={null} onUseStep={() => {}} />);
    expect(screen.getByRole('region', { name: `SOP ${kind}` })).toBeTruthy();
    expect(screen.getByText('Disconnect power.')).toBeTruthy();
    expect(screen.getByText('Citations')).toBeTruthy();
  });

  it('does not render unverified generated content on either display', () => {
    const res = { ...response('warning'), verified: false };
    expect(receive(res).screen).toBe('ERROR');
    render(<AnswerDetail res={res} pinnedStepId={null} onUseStep={() => {}} />);
    expect(screen.queryByRole('region', { name: 'SOP warning' })).toBeNull();
    expect(screen.queryByText('Disconnect power.')).toBeNull();
  });

  it('supports old responses and the single answer layout', () => {
    expect(receive(structuredClone(UI_FIXTURES.answer)).screen).toBe('ANSWER_GLANCE');
    expect(receive(response('answer')).screen).toBe('ANSWER_GLANCE');
  });

  it.each([null, { kind: 'html', items: ['unsafe'] }, { kind: 'warning', items: [] },
    { kind: 'checklist', items: ['x'.repeat(181)] }, { kind: 'warning', items: [''] },
    { kind: 'warning', items: [1] }, { kind: 'warning', items: ['x', 'x', 'x', 'x', 'x'] },
  ])('ignores malformed or unsupported display data: %j', value => {
    expect(parseDisplay(value)).toBeNull();
  });
});
