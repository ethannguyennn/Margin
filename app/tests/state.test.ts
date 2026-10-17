import { describe, expect, it } from 'vitest';
import { initialState, transition, restoreSession, serializeSession, timeoutFor, WALKTHROUGH_TTL_MS,
  type Screen, type Gesture } from '../src/state';
import { UI_FIXTURES } from '../src/ui/fixtures';

import { stateFor } from './support';

// Every state x gesture, including intentional no-ops. Columns: press, double, up, down, long.
const map: Record<Screen, Screen[]> = {
  PRIVACY: ['IDLE','PRIVACY','PRIVACY','PRIVACY','PRIVACY'],
  IDLE: ['LISTENING','IDLE','IDLE','IDLE','IDLE'],
  LISTENING: ['THINKING','IDLE','LISTENING','LISTENING','LISTENING'],
  THINKING: ['THINKING','IDLE','THINKING','THINKING','THINKING'],
  ANSWER_GLANCE: ['ANSWER_EXPANDED','IDLE','ANSWER_GLANCE','ANSWER_GLANCE','ANSWER_GLANCE'],
  ANSWER_EXPANDED: ['ANSWER_GLANCE','ANSWER_GLANCE','ANSWER_EXPANDED','ANSWER_EXPANDED','ANSWER_EXPANDED'],
  NOT_FOUND: ['LISTENING','IDLE','NOT_FOUND','NOT_FOUND','NOT_FOUND'],
  WALKTHROUGH: ['ANSWER_EXPANDED','IDLE','WALKTHROUGH','WALKTHROUGH','WALKTHROUGH'],
  LOGGED: ['IDLE','IDLE','LOGGED','LOGGED','LOGGED'],
  ERROR: ['LISTENING','IDLE','ERROR','ERROR','ERROR'],
};
const gestures: Gesture[] = ['PRESS','DOUBLE_PRESS','UP','DOWN','LONG_PRESS'];

describe('state/gesture matrix', () => {
  for (const [screen, targets] of Object.entries(map)) for (const [index, type] of gestures.entries()) {
    it(`${screen} + ${type} -> ${targets[index]}`, () => {
      const result = transition(stateFor(screen as Screen), { type });
      expect(result.state.screen).toBe(targets[index]);
      if (type === 'DOUBLE_PRESS' && (screen === 'IDLE' || screen === 'PRIVACY')) expect(result.effects).toEqual(['EXIT']);
      if (type === 'PRESS' && ['IDLE','NOT_FOUND','ERROR'].includes(screen)) expect(result.effects).toEqual(['START_CAPTURE']);
      if (type === 'PRESS' && screen === 'LISTENING') expect(result.effects).toEqual(['STOP_AND_SEND']);
    });
  }
  for (const screen of Object.keys(map) as Screen[]) {
    it(`${screen} times out and cancels in-flight work`, () => {
      const result = transition(stateFor(screen), { type: 'TIMEOUT' });
      expect(result.state.screen).toBe('IDLE'); expect(result.effects).toEqual(['CANCEL']);
    });
    it(`${screen} fails safely`, () => expect(transition(stateFor(screen), { type: 'FAIL' }).state.screen).toBe('ERROR'));
    if (screen !== 'THINKING') it(`${screen} ignores late responses`, () => {
      const state = stateFor(screen);
      expect(transition(state, { type: 'RESPONSE', response: UI_FIXTURES.answer, now: 0 }).state).toBe(state);
    });
  }
});

describe('response trust routing', () => {
  it.each([['answer','ANSWER_GLANCE'],['not_found','NOT_FOUND'],['error','ERROR'],['walkthrough','WALKTHROUGH'],['logged','LOGGED']] as const)('%s -> %s', (fixture, screen) => {
    expect(transition(stateFor('THINKING'), { type: 'RESPONSE', response: UI_FIXTURES[fixture], now: 1000 }).state.screen).toBe(screen);
  });
  for (const name of ['answer','walkthrough','logged'] as const) it(`refuses unverified ${name}`, () => {
    const response = { ...UI_FIXTURES[name], verified: false, glance: 'UNSAFE' };
    const state = transition(stateFor('THINKING'), { type: 'RESPONSE', response, now: 1000 }).state;
    expect(state.screen).toBe('ERROR'); expect(state.response).toBeNull(); expect(state.walkthrough).toBeNull();
  });
  it('clarify is never treated as a verified answer', () => {
    expect(transition(stateFor('THINKING'), { type: 'RESPONSE', response: { ...UI_FIXTURES.answer, outcome: 'clarify' }, now: 1000 }).state.screen).toBe('ERROR');
  });
  it('refuses invalid walkthroughs and impossible word pagination', () => {
    const response = structuredClone(UI_FIXTURES.walkthrough); response.walkthrough!.total = 99;
    expect(transition(stateFor('THINKING'), { type: 'RESPONSE', response, now: 1000 }).state.screen).toBe('ERROR');
    expect(transition(stateFor('THINKING'), { type: 'RESPONSE', response: { ...UI_FIXTURES.answer, body: 'a'.repeat(451) }, now: 1000 }).state.screen).toBe('ERROR');
  });
  it('prioritizes not_found and error over a supplied walkthrough', () => {
    for (const [outcome, expected] of [['not_found','NOT_FOUND'],['error','ERROR']] as const) {
      expect(transition(stateFor('THINKING'), { type: 'RESPONSE', response: { ...UI_FIXTURES.walkthrough, outcome }, now: 1 }).state.screen).toBe(expected);
    }
  });
});

describe('local navigation', () => {
  it('walks two steps, clamps boundaries, opens details and returns to the same step', () => {
    let state = stateFor('WALKTHROUGH');
    state = transition(state, { type: 'UP' }).state; expect(state.walkthrough!.index).toBe(0);
    state = transition(state, { type: 'DOWN' }).state;
    state = transition(state, { type: 'PRESS' }).state;
    expect(state.screen).toBe('ANSWER_EXPANDED'); expect(state.pages.length).toBeGreaterThan(1);
    state = transition(state, { type: 'DOWN' }).state; expect(state.page).toBe(1);
    state = transition(state, { type: 'UP' }).state; expect(state.page).toBe(0);
    state = transition(state, { type: 'DOUBLE_PRESS' }).state;
    expect(state.screen).toBe('WALKTHROUGH'); expect(state.walkthrough!.index).toBe(1);
    state = transition(state, { type: 'DOWN' }).state;
    state = transition(state, { type: 'DOWN' }).state; expect(state.walkthrough!.index).toBe(2);
    state = transition(state, { type: 'PRESS' }).state;
    state = transition(state, { type: 'PRESS' }).state; expect(state.screen).toBe('WALKTHROUGH');
  });
  it('clamps ordinary detail pages', () => {
    const state = { ...stateFor('ANSWER_EXPANDED'), pages: ['one', 'two'] };
    expect(transition(state, { type: 'UP' }).state.page).toBe(0);
    const last = transition(state, { type: 'DOWN' }).state;
    expect(last.page).toBe(1); expect(transition(last, { type: 'DOWN' }).state.page).toBe(1);
  });
});

describe('persistence and lifecycle policy', () => {
  it('restores session, privacy, mic source, revision, index, and every local step on cold start', () => {
    let state = stateFor('WALKTHROUGH');
    state = { ...transition(state, { type: 'DOWN' }).state, micSource: 'phone' };
    const restored = restoreSession(serializeSession(state), 2000, 'replacement-session');
    expect(restored.screen).toBe('WALKTHROUGH'); expect(restored.session_id).toBe('session-test');
    expect(restored.privacySeen).toBe(true); expect(restored.micSource).toBe('phone');
    expect(restored.walkthrough).toEqual(state.walkthrough);
    expect(transition(restored, { type: 'PRESS' }).state.screen).toBe('ANSWER_EXPANDED');
  });
  it.each([WALKTHROUGH_TTL_MS, WALKTHROUGH_TTL_MS + 1, -1])('discards stale or future walkthrough at age %i', age => {
    expect(restoreSession(serializeSession(stateFor('WALKTHROUGH')), 1000 + age, 'new').screen).toBe('IDLE');
  });
  it('restores a walkthrough just inside the 30 minute boundary', () => {
    expect(restoreSession(serializeSession(stateFor('WALKTHROUGH')), 1000 + WALKTHROUGH_TTL_MS - 1, 'new').screen).toBe('WALKTHROUGH');
  });
  it('shows privacy once, never marks it seen on exit', () => {
    const fresh = initialState('session');
    expect(restoreSession('', 1000, 'session').screen).toBe('PRIVACY');
    expect(transition(fresh, { type: 'DOUBLE_PRESS' }).state.privacySeen).toBe(false);
    const accepted = transition(fresh, { type: 'PRESS' }).state;
    expect(restoreSession(serializeSession(accepted), 1000, 'new').screen).toBe('IDLE');
  });
  it.each(['{broken','null','{"version":2}', '{}'])('handles corrupt storage %s', raw => {
    expect(restoreSession(raw, 1000, 'fresh')).toEqual(initialState('fresh'));
  });
  it('never stores an ordinary answer, transcript or audio', () => {
    const saved = serializeSession(stateFor('ANSWER_GLANCE'));
    expect(saved).not.toContain('Torque'); expect(saved).not.toContain('transcript'); expect(saved).not.toContain('data_b64');
  });
  it('arms 20s only for glance; walkthrough and its details persist', () => {
    expect(timeoutFor(stateFor('ANSWER_GLANCE'))).toBe(20_000);
    expect(timeoutFor(stateFor('ANSWER_EXPANDED'))).toBe(60_000);
    expect(timeoutFor(stateFor('WALKTHROUGH'))).toBeNull();
    expect(timeoutFor(transition(stateFor('WALKTHROUGH'), { type: 'PRESS' }).state)).toBeNull();
    expect(timeoutFor(stateFor('PRIVACY'))).toBeNull();
    expect(timeoutFor(stateFor('IDLE'))).toBeNull();
  });
});
