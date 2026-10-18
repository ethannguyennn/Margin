// The phone screen <-> lens seam: typed questions through the lens controller, and
// the LensLink the React phone UI subscribes to. No React, SDK or network here.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LensController, transition, type LensPorts } from '../src/state';
import { LensLink } from '../src/lens-link';
import type { AskResponse } from '../src/types';
import { UI_FIXTURES } from '../src/ui/fixtures';
import { stateFor } from './support';

function ports(): LensPorts {
  return { render: vi.fn(async () => {}), persist: vi.fn(async () => {}),
    startCapture: vi.fn(async () => {}), stopCapture: vi.fn(async () => ({ data_b64: 'fixture-audio', sample_rate: 16000 as const })),
    ask: vi.fn(async () => structuredClone(UI_FIXTURES.answer)), exit: vi.fn(async () => {}), now: Date.now, onError: vi.fn() };
}
const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
const CTX = { doc_id: 'SOP-114', step_id: 'SOP-114:C:4.2' };

describe('TEXT_ASK transition', () => {
  it.each(['IDLE', 'NOT_FOUND', 'ERROR', 'ANSWER_GLANCE', 'ANSWER_EXPANDED', 'WALKTHROUGH', 'LOGGED'] as const)(
    'goes from %s to THINKING, cancelling any open mic first', screen => {
      const { state, effects } = transition(stateFor(screen), { type: 'TEXT_ASK' });
      expect(state.screen).toBe('THINKING');
      expect(effects).toEqual(['CANCEL', 'SEND_TEXT']);
      expect(state.response).toBeNull();
    });
  it('cancels a live capture when typed from LISTENING', () => {
    const { state, effects } = transition(stateFor('LISTENING'), { type: 'TEXT_ASK' });
    expect(state.screen).toBe('THINKING'); expect(effects[0]).toBe('CANCEL');
  });
  it.each(['THINKING', 'PRIVACY'] as const)('is ignored on %s', screen => {
    const before = stateFor(screen);
    const { state, effects } = transition(before, { type: 'TEXT_ASK' });
    expect(state).toBe(before); expect(effects).toEqual([]);
  });
});

describe('LensController.askText', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('sends a text request under the lens session and shows the answer on the lens', async () => {
    const p = ports(); const c = new LensController(stateFor('IDLE'), p); await c.start();
    expect(c.askText('  how tight is the m5  ', CTX)).toBe(true);
    expect(c.state.screen).toBe('THINKING'); await settle();
    expect(p.ask).toHaveBeenCalledTimes(1);
    expect(p.ask).toHaveBeenCalledWith(
      { session_id: 'session-test', text: 'how tight is the m5', revision: null, context: CTX },
      expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(p.startCapture).not.toHaveBeenCalled();
    expect(c.state.screen).toBe('ANSWER_GLANCE');
    await c.dispose();
  });

  it('closes the mic before sending when the lens was listening', async () => {
    const p = ports(); const order: string[] = [];
    p.stopCapture = vi.fn(async () => { order.push('stop'); return { data_b64: '', sample_rate: 16000 as const }; });
    p.ask = vi.fn(async () => { order.push('ask'); return structuredClone(UI_FIXTURES.answer); });
    const c = new LensController(stateFor('IDLE'), p); await c.start();
    c.dispatch({ type: 'PRESS' }); await settle(); expect(c.state.screen).toBe('LISTENING');
    expect(c.askText('repeat')).toBe(true); await settle();
    expect(order).toEqual(['stop', 'ask']);
    expect(p.ask).toHaveBeenCalledWith(expect.objectContaining({ text: 'repeat' }), expect.anything());
    expect(p.ask).toHaveBeenCalledTimes(1); // the cancelled audio was never sent
    await c.dispose();
  });

  it('refuses while a question is in flight, on the privacy notice, or when blank', async () => {
    const p = ports(); let finish!: (r: AskResponse) => void;
    p.ask = vi.fn(() => new Promise(resolve => { finish = resolve; }));
    const c = new LensController(stateFor('IDLE'), p); await c.start();
    expect(c.askText('   ')).toBe(false);
    expect(c.askText('first')).toBe(true); await settle();
    expect(c.askText('second')).toBe(false);
    finish(structuredClone(UI_FIXTURES.answer)); await settle();
    expect(p.ask).toHaveBeenCalledTimes(1);
    const privacy = new LensController(stateFor('PRIVACY'), ports()); await privacy.start();
    expect(privacy.askText('hello')).toBe(false); expect(privacy.state.screen).toBe('PRIVACY');
    await c.dispose(); await privacy.dispose();
  });

  it('drops the answer to a typed question cancelled on the glasses', async () => {
    const p = ports(); let finish!: (r: AskResponse) => void;
    p.ask = vi.fn(() => new Promise(resolve => { finish = resolve; }));
    const c = new LensController(stateFor('IDLE'), p); await c.start();
    c.askText('how tight'); await settle();
    c.dispatch({ type: 'DOUBLE_PRESS' }); expect(c.state.screen).toBe('IDLE');
    finish(structuredClone(UI_FIXTURES.answer)); await settle();
    expect(c.state.screen).toBe('IDLE');
    await c.dispose();
  });

  it('fails to ERROR when the relay call rejects', async () => {
    const p = ports(); p.ask = vi.fn(async () => { throw new Error('relay down'); });
    const c = new LensController(stateFor('IDLE'), p); await c.start();
    c.askText('how tight'); await settle();
    expect(c.state.screen).toBe('ERROR'); expect(p.onError).toHaveBeenCalled();
    await c.dispose();
  });
});

describe('LensLink', () => {
  it('starts disconnected and refuses commands until attached', () => {
    const link = new LensLink();
    expect(link.getSnapshot()).toMatchObject({ connected: false, screen: null, sessionId: null });
    expect(link.askText('hi', CTX)).toBe(false);
    expect(link.canTogglePushToTalk()).toBe(false);
  });

  it('notifies subscribers only on real changes and keeps the snapshot stable', () => {
    const link = new LensLink(); const seen = vi.fn(); link.subscribe(seen);
    const first = link.getSnapshot();
    link.update({ status: first.status }); expect(seen).not.toHaveBeenCalled();
    expect(link.getSnapshot()).toBe(first);
    link.update({ screen: 'IDLE' }); expect(seen).toHaveBeenCalledTimes(1);
    expect(link.getSnapshot()).not.toBe(first);
  });

  it('forwards commands once attached and clears them on detach', () => {
    const link = new LensLink();
    const commands = { askText: vi.fn(() => true), togglePushToTalk: vi.fn() };
    link.attach(commands, 'lens-session');
    expect(link.getSnapshot()).toMatchObject({ connected: true, sessionId: 'lens-session' });
    expect(link.askText('hi', CTX)).toBe(true); expect(commands.askText).toHaveBeenCalledWith('hi', CTX);
    link.detach('closed');
    expect(link.getSnapshot()).toMatchObject({ connected: false, screen: null, status: 'closed' });
    expect(link.askText('hi', CTX)).toBe(false);
  });

  it.each([
    ['IDLE', true], ['NOT_FOUND', true], ['ERROR', true], ['LISTENING', true],
    ['THINKING', false], ['ANSWER_GLANCE', false], ['WALKTHROUGH', false], ['PRIVACY', false],
  ] as const)('push-to-talk on %s: %s', (screen, allowed) => {
    const link = new LensLink(); const commands = { askText: vi.fn(() => true), togglePushToTalk: vi.fn() };
    link.attach(commands, 's'); link.update({ screen });
    expect(link.canTogglePushToTalk()).toBe(allowed);
    link.togglePushToTalk();
    expect(commands.togglePushToTalk).toHaveBeenCalledTimes(allowed ? 1 : 0);
  });

  it('delivers every exchange to every listener until unsubscribed', () => {
    const link = new LensLink(); const a = vi.fn(); const b = vi.fn();
    const offA = link.onExchange(a); link.onExchange(b);
    const exchange = { response: structuredClone(UI_FIXTURES.answer), question: null };
    link.publishExchange(exchange); offA(); link.publishExchange(exchange);
    expect(a).toHaveBeenCalledTimes(1); expect(b).toHaveBeenCalledTimes(2);
    expect(b).toHaveBeenCalledWith(exchange);
  });
});
