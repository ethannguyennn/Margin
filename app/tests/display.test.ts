import { describe, expect, it, vi } from 'vitest';
import { CONTAINERS, createLayout, LensDisplay } from '../src/ui/layout';
import { renderScreen } from '../src/ui/screens';
import { sanitizeForG2 } from '../src/ui/glyphs';
import { stateFor } from './support';
import type { Screen } from '../src/state';
import { gestureFromEvent } from '../src/ui/input';

describe('lens screens/layout', () => {
  const screens: Screen[] = ['PRIVACY','IDLE','LISTENING','THINKING','ANSWER_GLANCE','ANSWER_EXPANDED','NOT_FOUND','WALKTHROUGH','LOGGED','ERROR'];
  for (const screen of screens) it(`renders ${screen} within the character and container budget`, () => {
    const text = renderScreen(stateFor(screen), 0.8);
    expect(Object.values(text).join('').length).toBeLessThanOrEqual(450);
    for (const value of Object.values(text)) expect(sanitizeForG2(value)).toBe(value);
    const layout = createLayout(text);
    expect(layout.containerTotalNum).toBe(3);
    expect(layout.textObject!.filter(c => c.isEventCapture === 1)).toHaveLength(1);
    expect(layout.textObject!.every(c => c.zOrderIndex === undefined)).toBe(true);
    expect(layout.textObject!.every(c => (c.content?.length ?? 0) <= 1000)).toBe(true);
  });
  it('positions non-overlapping containers inside the canvas with explicit brightness', () => {
    for (const c of CONTAINERS) {
      expect(c.yPosition + c.height).toBeLessThanOrEqual(288);
      expect(c.textColor).toBeGreaterThan(0); expect(c.textColor).toBeLessThanOrEqual(4);
    }
    expect(new Set(CONTAINERS.map(c => c.containerID)).size).toBe(3);
  });
  it('starts once and upgrades only changed text for every subsequent screen', async () => {
    const bridge = { createStartUpPageContainer: vi.fn(async () => 0), textContainerUpgrade: vi.fn(async () => true) };
    const display = new LensDisplay(bridge);
    for (const screen of screens) await display.render(renderScreen(stateFor(screen)));
    expect(bridge.createStartUpPageContainer).toHaveBeenCalledTimes(1);
    const before = bridge.textContainerUpgrade.mock.calls.length;
    await display.render(renderScreen(stateFor('ERROR')));
    expect(bridge.textContainerUpgrade).toHaveBeenCalledTimes(before);
  });
  it('surfaces startup and update failures', async () => {
    await expect(new LensDisplay({ createStartUpPageContainer: async () => 1, textContainerUpgrade: async () => true }).render(renderScreen(stateFor('IDLE')))).rejects.toThrow('Startup');
    const display = new LensDisplay({ createStartUpPageContainer: async () => 0, textContainerUpgrade: async () => false });
    await display.render(renderScreen(stateFor('IDLE')));
    await expect(display.render(renderScreen(stateFor('ERROR')))).rejects.toThrow('Text update');
  });
  it('renders safe static copy even if NOT_FOUND/ERROR contains hostile response text', () => {
    for (const screen of ['NOT_FOUND','ERROR'] as const) {
      const state = stateFor('ANSWER_GLANCE'); state.screen = screen;
      state.response = { ...state.response!, verified: false, glance: 'UNSAFE', body: 'UNSAFE' };
      expect(JSON.stringify(renderScreen(state))).not.toContain('UNSAFE');
    }
  });
  it('refuses unverified glance/expanded text even if passed directly to the renderer', () => {
    for (const screen of ['ANSWER_GLANCE','ANSWER_EXPANDED'] as const) {
      const state = stateFor(screen); state.response!.verified = false;
      expect(renderScreen(state).header).toBe('ERROR');
    }
  });
});

describe('SDK event routing', () => {
  it.each([
    [{ sysEvent: {} }, 'PRESS'], [{ sysEvent: { eventType: 0 } }, 'PRESS'],
    [{ textEvent: { containerID: 2, eventType: 0 } }, 'PRESS'],
    [{ sysEvent: { eventType: 3 } }, 'DOUBLE_PRESS'], [{ textEvent: { eventType: 3 } }, 'DOUBLE_PRESS'],
    [{ textEvent: { containerID: 2, eventType: 1 } }, 'UP'], [{ textEvent: { containerID: 2, eventType: 2 } }, 'DOWN'],
    [{ sysEvent: { eventType: 9 } }, 'LONG_PRESS'], [{ sysEvent: { eventType: 10 } }, 'LONG_PRESS'],
    [{}, null], [{ sysEvent: { eventType: 4 } }, null], [{ textEvent: { containerID: 999, eventType: 1 } }, null],
  ] as const)('routes %j to %s', (event, expected) => expect(gestureFromEvent(event)).toBe(expected));
  it('ignores audio and never interprets missing sysEvent as a click', () => {
    expect(gestureFromEvent({ audioEvent: { source: 'glasses' as never, audioPcm: new Uint8Array(3200) } })).toBeNull();
  });
});
