import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SessionStore } from '../src/ui/session-store';
describe('debounced native session persistence', () => {
  beforeEach(() => vi.useFakeTimers()); afterEach(() => vi.useRealTimers());
  it('coalesces rapid navigation into the latest value and settles every caller', async () => {
    const write = vi.fn(async () => true); const store = new SessionStore(write);
    const callers = [store.save('step 1'), store.save('step 2'), store.save('step 3')];
    await vi.advanceTimersByTimeAsync(149); expect(write).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1); await Promise.all(callers);
    expect(write).toHaveBeenCalledExactlyOnceWith('step 3');
    await store.save('step 3'); expect(write).toHaveBeenCalledTimes(1);
  });
  it('flushes immediately for background/exit when requested', async () => {
    const write = vi.fn(async () => true); const store = new SessionStore(write);
    const saved = store.save('state'); await store.flush(); await saved;
    expect(write).toHaveBeenCalledExactlyOnceWith('state');
  });
  it('serializes a later save behind an outstanding write', async () => {
    let finish!: (ok: boolean) => void;
    const write = vi.fn(() => new Promise<boolean>(resolve => { finish = resolve; }));
    const store = new SessionStore(write);
    const first = store.save('first'); await vi.advanceTimersByTimeAsync(150);
    const second = store.save('second'); await vi.advanceTimersByTimeAsync(150);
    expect(write).toHaveBeenCalledTimes(1); finish(true); await first;
    for (let i = 0; i < 10; i++) await Promise.resolve();
    expect(write).toHaveBeenCalledTimes(2); finish(true); await second;
  });
  it('rejects failed writes and permits a later retry', async () => {
    const write = vi.fn(async () => false); const store = new SessionStore(write);
    const failed = store.save('state'); const assertion = expect(failed).rejects.toThrow('storage');
    await vi.advanceTimersByTimeAsync(150); await assertion;
    write.mockResolvedValue(true); const retry = store.save('state'); await vi.advanceTimersByTimeAsync(150); await retry;
    expect(write).toHaveBeenCalledTimes(2);
  });
  it('settles a newer save even if an in-flight write fails', async () => {
    let finish!: (ok: boolean) => void;
    const write = vi.fn(() => new Promise<boolean>(resolve => { finish = resolve; }));
    const store = new SessionStore(write);
    const first = store.save('first'); const firstCheck = expect(first).rejects.toThrow('storage');
    await vi.advanceTimersByTimeAsync(150);
    const second = store.save('second'); await vi.advanceTimersByTimeAsync(150);
    finish(false); await firstCheck;
    for (let i = 0; i < 10; i++) await Promise.resolve();
    expect(write).toHaveBeenCalledTimes(2); finish(true); await second;
  });
});
