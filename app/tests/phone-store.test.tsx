// @vitest-environment jsdom
// The phone screen's store: linked to the lens (typed asks go through the lens
// controller, every lens answer shows up here) and standalone (browser preview).
import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { lensLink } from '../src/lens-link';
import type { AskResponse } from '../src/types';
import { UI_FIXTURES } from '../src/ui/fixtures';

const relay = vi.hoisted(() => ({
  health: vi.fn(async () => ({ ok: true, mock: true, db: 'mock', version: 'test' })),
  ask: vi.fn(),
  logDeviation: vi.fn(async () => ({ deviation_id: 'DEV-0001', notified: true })),
}));
vi.mock('../src/phone/relay', () => ({
  ...relay,
  relayOrigin: 'http://relay.test',
  asRelayError: (e: unknown) => ({ code: 'network', message: String(e) }),
  listProcedures: vi.fn(async () => []),
  listSteps: vi.fn(async () => []),
}));

const { StoreProvider, useStore } = await import('../src/phone/store');
const wrapper = ({ children }: { children: ReactNode }) => <StoreProvider>{children}</StoreProvider>;
const answer = (): AskResponse => structuredClone(UI_FIXTURES.answer);

function attachLens(askText: (text: string) => boolean = () => true) {
  const commands = { askText: vi.fn((text: string, _context: unknown) => askText(text)), togglePushToTalk: vi.fn() };
  act(() => { lensLink.attach(commands, '11111111-1111-4111-8111-111111111111'); lensLink.update({ screen: 'IDLE' }); });
  return commands;
}

beforeEach(() => { localStorage.clear(); vi.clearAllMocks(); });
afterEach(() => { cleanup(); act(() => lensLink.detach('test reset')); });

describe('phone store, linked to the lens', () => {
  it('asks through the lens under the lens session and records the answer', async () => {
    const commands = attachLens();
    const { result } = renderHook(useStore, { wrapper });
    expect(result.current.sessionId).toBe('11111111-1111-4111-8111-111111111111');
    let pending!: Promise<AskResponse | null>;
    act(() => { pending = result.current.askNow('  how tight is the m5 '); });
    expect(commands.askText).toHaveBeenCalledWith('how tight is the m5', { doc_id: null, step_id: null });
    expect(relay.ask).not.toHaveBeenCalled(); // the lens client makes the relay call
    const res = answer();
    act(() => { lensLink.update({ screen: 'THINKING' }); lensLink.publishExchange({ response: res, question: 'how tight is the m5' }); });
    await expect(pending).resolves.toEqual(res);
    await waitFor(() => expect(result.current.busy).toBeNull());
    expect(result.current.state.lastAnswer).toEqual(res);
    expect(result.current.state.history[0]).toMatchObject({ question: 'how tight is the m5', outcome: res.outcome });
  });

  it('shows answers to questions spoken on the glasses', () => {
    attachLens();
    const { result } = renderHook(useStore, { wrapper });
    const res = { ...answer(), transcript: 'spoken on the glasses' };
    act(() => lensLink.publishExchange({ response: res, question: null }));
    expect(result.current.state.lastAnswer).toEqual(res);
    expect(result.current.state.history[0].question).toBe('spoken on the glasses');
  });

  it('explains a refusal on the privacy notice instead of hanging', async () => {
    attachLens(() => false);
    act(() => lensLink.update({ screen: 'PRIVACY' }));
    const { result } = renderHook(useStore, { wrapper });
    let res: AskResponse | null = answer();
    await act(async () => { res = await result.current.askNow('hello'); });
    expect(res).toBeNull();
    expect(result.current.error?.code).toBe('privacy');
    expect(result.current.busy).toBeNull();
  });

  it('stops waiting when the lens leaves THINKING without an answer (cancelled on the glasses)', async () => {
    attachLens();
    const { result } = renderHook(useStore, { wrapper });
    let pending!: Promise<AskResponse | null>;
    act(() => { pending = result.current.askNow('how tight'); });
    act(() => lensLink.update({ screen: 'THINKING' }));
    act(() => lensLink.update({ screen: 'IDLE' }));
    await expect(pending).resolves.toBeNull();
  });

  it('surfaces a contract error answer as the error banner', () => {
    attachLens();
    const { result } = renderHook(useStore, { wrapper });
    const failed = { ...answer(), outcome: 'error' as const, error: { code: 'llm_timeout', message: 'slow' } };
    act(() => lensLink.publishExchange({ response: failed, question: 'boom' }));
    expect(result.current.error).toEqual({ code: 'llm_timeout', message: 'slow' });
  });

  it('push-to-talk is only offered on resting screens and forwards to the lens', () => {
    const commands = attachLens();
    const { result } = renderHook(useStore, { wrapper });
    expect(result.current.canPushToTalk).toBe(true);
    act(() => result.current.togglePushToTalk());
    expect(commands.togglePushToTalk).toHaveBeenCalledTimes(1);
    act(() => lensLink.update({ screen: 'ANSWER_GLANCE' }));
    expect(result.current.canPushToTalk).toBe(false);
    act(() => lensLink.update({ screen: 'LISTENING' }));
    expect(result.current.state.listening).toBe(true);
  });

  it('mic source writes the setting the capture module reads', () => {
    attachLens();
    const { result } = renderHook(useStore, { wrapper });
    act(() => result.current.setMicSource('phone'));
    expect(localStorage.getItem('margin.micSource')).toBe('phone');
    expect(result.current.state.micSource).toBe('phone');
  });
});

describe('phone store, standalone (browser preview, no glasses)', () => {
  it('asks the relay directly under its own session', async () => {
    const res = answer();
    relay.ask.mockResolvedValueOnce(res);
    const { result } = renderHook(useStore, { wrapper });
    expect(result.current.lens.connected).toBe(false);
    let got: AskResponse | null = null;
    await act(async () => { got = await result.current.askNow('how tight'); });
    expect(got).toEqual(res);
    expect(relay.ask).toHaveBeenCalledWith(result.current.state.sessionId, 'how tight', { doc_id: null, step_id: null });
    expect(result.current.state.history).toHaveLength(1);
    expect(result.current.canPushToTalk).toBe(false);
  });
});
