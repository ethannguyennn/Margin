// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mountSimulator } from '../src/simulator/simulator';
import { BrowserLensDisplay, tileSource } from '../src/simulator/display';
import { UI_FIXTURES, taskFixture } from '../src/ui/fixtures';
import type { AskResponse } from '../src/types';

let dispose: (() => void) | undefined;
afterEach(() => { dispose?.(); dispose = undefined; document.body.replaceChildren(); });

function setup(ask = vi.fn(async () => structuredClone(UI_FIXTURES.answer))) {
  const host = document.createElement('div'); document.body.append(host);
  const exchange = vi.fn();
  const mounted = mountSimulator(host, { sessionId: 'browser-test', ask, onExchange: exchange });
  dispose = mounted.dispose;
  return { ...mounted, ask, host, exchange };
}
function click(name: string) {
  const button = [...document.querySelectorAll('button')].find(b => b.textContent === name)!;
  expect(button).toBeTruthy(); button.click();
}
function send(text: string) {
  const input = document.querySelector('input')!; input.value = text; input.dispatchEvent(new Event('input'));
  document.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true }));
}

describe('browser glasses simulator', () => {
  it('updates through real thinking/answer/detail states and records one exchange', async () => {
    let finish!: (response: AskResponse) => void;
    const { ask, exchange } = setup(vi.fn(() => new Promise<AskResponse>(resolve => { finish = resolve; })));
    send('How tight is the M5?');
    expect(document.querySelector('[data-screen="THINKING"]')).toBeTruthy();
    expect(document.querySelector('button[type=submit]')?.hasAttribute('disabled')).toBe(true);
    await vi.waitFor(() => expect(ask).toHaveBeenCalledTimes(1));
    finish(structuredClone(UI_FIXTURES.answer));
    await vi.waitFor(() => expect(document.querySelector('[data-screen="ANSWER_GLANCE"]')).toBeTruthy());
    expect(document.querySelector('.lens-sim-main')?.textContent).toContain('4 N-m');
    click('Tap');
    expect(document.querySelector('[data-screen="ANSWER_EXPANDED"]')).toBeTruthy();
    expect(exchange).toHaveBeenCalledTimes(1);
  });

  it('opens a walkthrough, navigates locally, and asks with the current step context', async () => {
    const ask = vi.fn().mockResolvedValueOnce(structuredClone(UI_FIXTURES.walkthrough)).mockResolvedValue(structuredClone(UI_FIXTURES.answer));
    const mounted = setup(ask);
    send('Walk me through the bracket');
    await vi.waitFor(() => expect(mounted.controller().state.screen).toBe('STEP'));
    click('Swipe down');
    expect(mounted.controller().state.walkthrough?.index).toBe(1);
    expect(ask).toHaveBeenCalledTimes(1);
    send('How tight here?');
    await vi.waitFor(() => expect(ask).toHaveBeenCalledTimes(2));
    expect(ask.mock.calls[1][0].context.step_id).toBe('2');
    await vi.waitFor(() => expect(mounted.controller().state.screen).toBe('ANSWER_GLANCE'));
    click('Double tap');
    expect(mounted.controller().state.screen).toBe('STEP');
    expect(mounted.controller().state.walkthrough?.index).toBe(1);
  });

  it('never renders an unverified answer', async () => {
    setup(vi.fn(async () => ({ ...structuredClone(UI_FIXTURES.answer), verified: false, glance: 'UNVERIFIED SECRET' })));
    send('Question');
    await vi.waitFor(() => expect(document.querySelector('[data-screen="ERROR"]')).toBeTruthy());
    expect(document.body.textContent).not.toContain('UNVERIFIED SECRET');
  });

  it('cancels in-flight requests on navigation and ignores late responses', async () => {
    let finish!: (response: AskResponse) => void;
    const ask = vi.fn((_request, _opts) => new Promise<AskResponse>(resolve => { finish = resolve; }));
    const mounted = setup(ask);
    send('Question');
    await vi.waitFor(() => expect(ask).toHaveBeenCalled());
    mounted.dispose(); dispose = undefined;
    expect(ask.mock.calls[0][1].signal.aborted).toBe(true);
    finish(structuredClone(UI_FIXTURES.answer));
    await Promise.resolve();
    expect(mounted.exchange).not.toHaveBeenCalled();
    expect(document.querySelector('.lens-simulator')).toBeNull();
  });

  it('supports simulated nod, empty capture cancellation, root exit and reset', async () => {
    const mounted = setup();
    click('Double nod'); expect(mounted.controller().state.screen).toBe('LISTENING');
    click('Double tap'); expect(mounted.controller().state.screen).toBe('IDLE');
    click('Double tap');
    await vi.waitFor(() => expect(document.body.textContent).toContain('Simulator closed'));
    click('Reset'); expect(mounted.controller().state.screen).toBe('IDLE');
    expect(document.body.textContent).not.toContain('Simulator closed');
    expect(mounted.ask).not.toHaveBeenCalled();
  });

  it('displays both diagram tiles and clears them on the next screen', async () => {
    const display = new BrowserLensDisplay(); document.body.append(display.element);
    const png = 'iVBORw0KGgo=';
    await display.render({ header: '', main: '', footer: 'Diagram' }, 'DIAGRAM', {
      diagram_id: 'test', tiles: [0, 1].map(slot => ({ slot: slot as 0 | 1, width: 288, height: 144, image: png })),
    });
    expect(display.element.querySelectorAll('img')).toHaveLength(2);
    await display.render({ header: '', main: 'Next step', footer: '' }, 'STEP');
    expect(display.element.querySelectorAll('img')).toHaveLength(0);
    expect(() => tileSource('AA==')).toThrow('Unsupported diagram format');
    display.dispose();
  });

  it('preserves warning text and uses the hardware screen renderer for task steps', async () => {
    const mounted = setup();
    mounted.controller().dispatch({ type: 'ASSIGNMENT', assignment: taskFixture(), now: Date.now() });
    click('Double nod');
    expect(document.querySelector('.lens-sim-main')?.textContent).toContain('Disconnect the training rig');
  });
});
