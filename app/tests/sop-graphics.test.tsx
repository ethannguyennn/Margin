// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ImageRawDataUpdateResult } from '@evenrealities/even_hub_sdk';
import { answerGraphic, getGraphic, stepGraphic, graphicAsset, GRAPHIC_WIDTH, GRAPHIC_HEIGHT } from '../src/ui/sop-graphics';
import { createLayout, GRAPHIC_CONTAINER, LensDisplay } from '../src/ui/layout';
import { renderScreen } from '../src/ui/screens';
import { initialState, transition } from '../src/state';
import { AnswerDetail } from '../src/phone/components/AnswerDetail';
import { Walkthrough } from '../src/phone/components/Walkthrough';
import { UI_FIXTURES } from '../src/ui/fixtures';
import type { AskResponse, Step } from '../src/types';

afterEach(cleanup);
const torque = 'Torque all four M5 bracket screws to 4 N-m in a star pattern.';
const gap = 'Check the gap between the bracket foot and housing with a 0.20 mm feeler gauge.';
const steps: Step[] = [
  { step_id: 'SOP-114:C:4.2', label: '4.2', glance: 'Fasten the M5 bracket screws', body: torque, graphic_id: 'bracket-fasteners' },
  { step_id: 'SOP-114:C:4.3', label: '4.3', glance: 'Check the bracket gap', body: gap, graphic_id: 'bracket-gap' },
];
function answer(): AskResponse {
  return { ...structuredClone(UI_FIXTURES.answer), graphic_id: 'bracket-fasteners',
    body: torque, citations: [{ chunk_id: 'SOP-114:C:4.2', doc_id: 'SOP-114', revision: 'C', section: '4.2', quote: torque }] };
}

describe('SOP reference images', () => {
  it('binds both explicit Gemini selections and old-relay citations to a local source image', () => {
    const res = answer();
    expect(answerGraphic(res)?.id).toBe('bracket-fasteners');
    delete res.graphic_id;
    expect(answerGraphic(res)?.id).toBe('bracket-fasteners');
    expect(graphicAsset(answerGraphic(res)!)).toContain('sop-114-bracket');
    res.graphic_id = null;
    expect(answerGraphic(res)).toBeNull();
  });

  it('rejects unknown URLs, uncited selections, wrong revisions and unverified images', () => {
    expect(answerGraphic({ ...answer(), graphic_id: 'https://unsafe.test/a.png' })).toBeNull();
    expect(answerGraphic({ ...answer(), graphic_id: 'housing-cleaning' })).toBeNull();
    expect(answerGraphic({ ...answer(), citations: [{ ...answer().citations[0], chunk_id: 'SOP-114:X:4.2' }] })).toBeNull();
    expect(answerGraphic({ ...answer(), verified: false })).toBeNull();
    expect(stepGraphic({ ...steps[0], step_id: 'SOP-114:X:4.2' })).toBeNull();
    const oldStep = { ...steps[1] }; delete oldStep.graphic_id;
    expect(stepGraphic(oldStep)?.id).toBe('bracket-gap');
  });

  it('shows an accompanying figure on the phone and changes the illustration with the step', () => {
    render(<AnswerDetail res={answer()} pinnedStepId={null} onUseStep={() => {}} />);
    expect(screen.getByRole('img', { name: /Synthetic close-up/ })).toBeTruthy();
    expect(screen.getByText(/Synthetic training reference/)).toBeTruthy();
    cleanup();
    render(<Walkthrough wt={{ doc_id: 'SOP-114', revision: 'C', title: 'Bracket', total: 2, index: 0, steps }}
      pinnedStepId={null} onUse={() => {}} />);
    expect(screen.getByRole('img', { name: /Synthetic close-up/ })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByRole('img', { name: /Synthetic side detail/ })).toBeTruthy();
  });

  it('uses the same graphic on glance/details and the matching graphic on each walkthrough step', () => {
    let state = transition({ ...initialState('image-test'), screen: 'THINKING' },
      { type: 'RESPONSE', response: answer(), now: 1 }).state;
    expect(renderScreen(state).graphic_id).toBe('bracket-fasteners');
    expect(state.pages.every(page => page.length <= 130)).toBe(true);
    state = transition(state, { type: 'PRESS' }).state;
    expect(renderScreen(state).graphic_id).toBe('bracket-fasteners');
    const walkthrough = { doc_id: 'SOP-114', revision: 'C', title: 'Bracket', total: 2, index: 0, steps };
    state = transition({ ...initialState('walk-test'), screen: 'THINKING' },
      { type: 'RESPONSE', response: { ...answer(), walkthrough }, now: 1 }).state;
    expect(renderScreen(state).graphic_id).toBe('bracket-fasteners');
    state = transition(state, { type: 'DOWN' }).state;
    expect(renderScreen(state).graphic_id).toBe('bracket-gap');
    state = transition(state, { type: 'PRESS' }).state;
    expect(renderScreen(state).graphic_id).toBe('bracket-gap');
  });

  it('keeps picture and instruction containers separate within SDK bounds', () => {
    const layout = createLayout({ header: 'SOP-114', main: torque, footer: 'source', graphic_id: 'bracket-fasteners' });
    expect(layout.containerTotalNum).toBe(4);
    expect(layout.imageObject).toHaveLength(1);
    const main = layout.textObject!.find(container => container.containerID === 2)!;
    expect(main.width!).toBeLessThan(GRAPHIC_CONTAINER.xPosition);
    expect(GRAPHIC_CONTAINER.width).toBeLessThanOrEqual(288);
    expect(GRAPHIC_CONTAINER.height).toBeLessThanOrEqual(144);
    expect(layout.textObject!.filter(container => container.isEventCapture === 1)).toHaveLength(1);
    expect(getGraphic('bracket-gap')!.crop[0]).toBeGreaterThan(0);
  });
});

describe('native image delivery', () => {
  function bridge() {
    return { createStartUpPageContainer: vi.fn(async () => 0), textContainerUpgrade: vi.fn(async () => true),
      rebuildPageContainer: vi.fn(async () => true), updateImageRawData: vi.fn(async () => ImageRawDataUpdateResult.success) };
  }
  const plain = { header: '', main: 'Ready', footer: 'press: ask' };
  it('rebuilds on picture entry/exit and sends Gray8 pixels only when the reference changes', async () => {
    const native = bridge();
    const rasterize = vi.fn(async () => new Uint8Array(GRAPHIC_WIDTH * GRAPHIC_HEIGHT).fill(255));
    const display = new LensDisplay(native, rasterize);
    await display.render(plain);
    await display.render({ ...plain, graphic_id: 'bracket-fasteners' });
    expect(native.rebuildPageContainer).toHaveBeenCalledTimes(1);
    expect(native.updateImageRawData.mock.calls[0][0].imageData).toHaveLength(288 * 144);
    await display.render({ ...plain, main: 'Next instruction', graphic_id: 'bracket-fasteners' });
    expect(native.updateImageRawData).toHaveBeenCalledTimes(1);
    await display.render({ ...plain, graphic_id: 'bracket-gap' });
    expect(native.rebuildPageContainer).toHaveBeenCalledTimes(1);
    expect(native.updateImageRawData).toHaveBeenCalledTimes(3);
    expect(Array.from(native.updateImageRawData.mock.calls[1][0].imageData as Uint8Array).every(value => value === 0)).toBe(true);
    await display.render(plain);
    expect(native.rebuildPageContainer).toHaveBeenCalledTimes(2);
    expect(native.rebuildPageContainer.mock.calls[1][0].imageObject).toBeUndefined();
  });

  it('surfaces image transport failures instead of silently dropping the picture', async () => {
    const native = bridge();
    native.updateImageRawData.mockResolvedValue(ImageRawDataUpdateResult.sendFailed);
    const display = new LensDisplay(native, async () => new Uint8Array(288 * 144));
    await display.render(plain);
    await expect(display.render({ ...plain, graphic_id: 'bracket-fasteners' })).rejects.toThrow('image update failed');
  });
});
