import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LensController, GLANCE_TIMEOUT_MS, type LensPorts } from '../src/state';
import type { AskResponse } from '../src/types';
import { UI_FIXTURES } from '../src/ui/fixtures';
import { stateFor } from './support';
import { BridgeQueue } from '../src/ui/bridge-queue';

function ports(): LensPorts {
  return { render: vi.fn(async () => {}), persist: vi.fn(async () => {}),
    startCapture: vi.fn(async () => {}), stopCapture: vi.fn(async () => ({ data_b64: 'fixture-audio', sample_rate: 16000 as const })),
    ask: vi.fn(async () => structuredClone(UI_FIXTURES.answer)), exit: vi.fn(async () => {}), now: Date.now, onError: vi.fn() };
}
const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
describe('controller effects and races', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());
  it('runs the complete gesture-only answer loop and glance timer', async () => {
    const p = ports(); const c = new LensController(stateFor('IDLE'), p); await c.start();
    c.dispatch({ type: 'PRESS' }); await settle(); expect(c.state.screen).toBe('LISTENING');
    c.dispatch({ type: 'PRESS' }); expect(c.state.screen).toBe('THINKING'); await settle();
    expect(c.state.screen).toBe('ANSWER_GLANCE'); expect(p.ask).toHaveBeenCalledTimes(1);
    expect(p.ask).toHaveBeenCalledWith(expect.objectContaining({ session_id: 'session-test', audio: { format: 'pcm_s16le', sample_rate: 16000, channels: 1, data_b64: 'fixture-audio' } }), expect.objectContaining({ signal: expect.any(AbortSignal) }));
    c.dispatch({ type: 'PRESS' }); expect(c.state.screen).toBe('ANSWER_EXPANDED');
    c.dispatch({ type: 'PRESS' }); expect(c.state.screen).toBe('ANSWER_GLANCE');
    await vi.advanceTimersByTimeAsync(GLANCE_TIMEOUT_MS - 1); expect(c.state.screen).toBe('ANSWER_GLANCE');
    await vi.advanceTimersByTimeAsync(1); expect(c.state.screen).toBe('IDLE');
    await c.dispose();
  });
  it('never calls the network during walkthrough step/page navigation', async () => {
    const p = ports(); const c = new LensController(stateFor('WALKTHROUGH'), p); await c.start();
    for (const type of ['DOWN','PRESS','DOWN','UP','DOUBLE_PRESS','DOWN'] as const) c.dispatch({ type });
    await vi.advanceTimersByTimeAsync(31 * 60_000);
    expect(c.state.screen).toBe('STEP'); expect(c.state.walkthrough!.index).toBe(2);
    expect(p.ask).not.toHaveBeenCalled(); expect(p.startCapture).not.toHaveBeenCalled(); await c.dispose();
  });
  it('drops late responses after cancel and after another request begins', async () => {
    const p = ports(); let finish!: (response: AskResponse) => void;
    p.ask = vi.fn(() => new Promise(resolve => { finish = resolve; }));
    const c = new LensController(stateFor('IDLE'), p); await c.start();
    c.dispatch({ type: 'PRESS' }); c.dispatch({ type: 'PRESS' }); await settle();
    c.dispatch({ type: 'DOUBLE_PRESS' }); await settle(); expect(c.state.screen).toBe('IDLE');
    c.dispatch({ type: 'PRESS' }); await settle();
    finish(UI_FIXTURES.answer); await settle(); expect(c.state.screen).toBe('LISTENING'); await c.dispose();
  });
  it('serializes stop after an in-flight start and refuses to send cancelled audio', async () => {
    const p = ports(); let started!: () => void;
    p.startCapture = vi.fn(() => new Promise(resolve => { started = resolve; }));
    const c = new LensController(stateFor('IDLE'), p); await c.start();
    c.dispatch({ type: 'PRESS' }); await settle(); c.dispatch({ type: 'PRESS' }); c.dispatch({ type: 'DOUBLE_PRESS' });
    expect(p.stopCapture).not.toHaveBeenCalled(); started(); await settle();
    expect(p.stopCapture).toHaveBeenCalled(); expect(p.ask).not.toHaveBeenCalled(); expect(c.state.screen).toBe('IDLE'); await c.dispose();
  });
  it.each(['start','stop','ask'] as const)('fails safely when %s rejects', async phase => {
    const p = ports();
    if (phase === 'start') p.startCapture = vi.fn(async () => { throw new Error('capture failed'); });
    if (phase === 'stop') p.stopCapture = vi.fn(async () => { throw new Error('stop failed'); });
    if (phase === 'ask') p.ask = vi.fn(async () => { throw new Error('relay failed'); });
    const c = new LensController(stateFor('IDLE'), p); await c.start();
    c.dispatch({ type: 'PRESS' }); await settle();
    if (phase !== 'start') { c.dispatch({ type: 'PRESS' }); await settle(); }
    expect(c.state.screen).toBe('ERROR'); expect(p.onError).toHaveBeenCalled();
    // Reset the failing port before disposal, which must stop audio too.
    p.stopCapture = vi.fn(async () => ({ data_b64: '', sample_rate: 16000 })); await c.dispose();
  });
  it('shows native exit confirmation at root and remains interactive if cancelled', async () => {
    const p = ports(); const c = new LensController(stateFor('IDLE'), p); await c.start();
    c.dispatch({ type: 'DOUBLE_PRESS' }); await settle(); expect(p.exit).toHaveBeenCalledTimes(1);
    expect(c.state.screen).toBe('IDLE'); c.dispatch({ type: 'PRESS' }); await settle();
    expect(c.state.screen).toBe('LISTENING'); await c.dispose();
  });
  it('suspends recording, discards requests, and re-renders on resume', async () => {
    const p = ports(); const c = new LensController(stateFor('IDLE'), p); await c.start();
    c.dispatch({ type: 'PRESS' }); await settle(); await c.suspend();
    expect(c.state.screen).toBe('IDLE'); await c.resume(); expect(p.render).toHaveBeenCalled(); await c.dispose();
  });
  it('preserves elapsed glance deadline across background/resume', async () => {
    const p = ports(); const c = new LensController(stateFor('ANSWER_GLANCE'), p); await c.start();
    await vi.advanceTimersByTimeAsync(10_000); await c.suspend();
    await vi.advanceTimersByTimeAsync(5000); await c.resume();
    await vi.advanceTimersByTimeAsync(4999); expect(c.state.screen).toBe('ANSWER_GLANCE');
    await vi.advanceTimersByTimeAsync(1); expect(c.state.screen).toBe('IDLE'); await c.dispose();
  });
  it('expires an overdue glance immediately on foreground', async () => {
    const c = new LensController(stateFor('ANSWER_GLANCE'), ports()); await c.start();
    await c.suspend(); await vi.advanceTimersByTimeAsync(21_000); await c.resume();
    expect(c.state.screen).toBe('IDLE'); await c.dispose();
  });
  it('stops capture and ignores all gestures on teardown', async () => {
    const p = ports(); const c = new LensController(stateFor('IDLE'), p); await c.start(); await c.dispose();
    c.dispatch({ type: 'PRESS' }); expect(c.state.screen).toBe('IDLE'); expect(p.stopCapture).toHaveBeenCalled();
  });
});

describe('bridge serialization', () => {
  it('never overlaps operations and recovers from ordinary rejections', async () => {
    const q = new BridgeQueue(); const order: number[] = [];
    let finish!: () => void;
    const first = q.run(() => new Promise<void>(resolve => { order.push(1); finish = resolve; }));
    const second = q.run(async () => { order.push(2); throw new Error('native refusal'); });
    const secondCheck = expect(second).rejects.toThrow('native refusal');
    await settle(); expect(order).toEqual([1]); finish(); await first; await secondCheck;
    await q.run(async () => { order.push(3); }); expect(order).toEqual([1,2,3]);
  });
  it('stops further native calls after an ambiguous timeout', async () => {
    vi.useFakeTimers();
    try {
      const q = new BridgeQueue(100); const operation = vi.fn(async () => 3);
      const stuck = q.run(() => new Promise(() => {}));
      const check = expect(stuck).rejects.toThrow('timed out');
      await vi.advanceTimersByTimeAsync(101); await check;
      await expect(q.run(operation)).rejects.toThrow('timed out'); expect(operation).not.toHaveBeenCalled();
    } finally { vi.useRealTimers(); }
  });
});
