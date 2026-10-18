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

import type { DiagramImage } from '../src/types';
import { DiagramRenderError } from '../src/ui/layout';
import { initialState } from '../src/state';
import { taskFixture } from '../src/ui/fixtures';
import { mockDiagramImage } from '../src/mock/tiles';
const tilesFor = (id: string) => ({ ...mockDiagramImage('dg-sop114-bracket')!, diagram_id: id });
describe('v2 display layouts and serial image updates',()=>{
  it('both layouts have one capture container and legal geometry',()=>{
    for(const layout of ['TEXT','DIAGRAM'] as const){
      const page=createLayout({header:'H',main:'M',footer:'F'},layout);
      expect(page.textObject!.filter(c=>c.isEventCapture===1)).toHaveLength(1);
      expect(page.textObject!.find(c=>c.isEventCapture===1)!.containerID).toBe(layout==='TEXT'?2:3);
      expect(page.textObject!.every(c=>c.zOrderIndex===undefined)).toBe(true);
      if(layout==='DIAGRAM'){
        expect(page.imageObject).toHaveLength(2);
        expect(page.imageObject!.map(c=>[c.xPosition,c.yPosition,c.width,c.height])).toEqual([[0,48,288,144],[288,48,288,144]]);
      }
    }
  });
  it('rebuild counter changes only for TEXT <-> DIAGRAM; every tile is awaited',async()=>{
    const calls:string[]=[];let active=0;
    const bridge={createStartUpPageContainer:vi.fn(async()=>0),textContainerUpgrade:vi.fn(async()=>{calls.push('text');return true;}),
      rebuildPageContainer:vi.fn(async()=>{calls.push('rebuild');return true;}),
      updateImageRawData:vi.fn(async(p:any)=>{active++;expect(active).toBe(1);calls.push(p.containerName);await Promise.resolve();active--;return 'success' as const;})};
    const d=new LensDisplay(bridge),text={header:'H',main:'M',footer:'caption'};
    const image=await Promise.resolve(tilesFor('test'));
    await d.render(text);await d.render({...text,main:'new text'});expect(d.rebuildCount).toBe(0);
    await d.render(text,'DIAGRAM',image);expect(d.rebuildCount).toBe(1);
    const first=calls.indexOf('rebuild');expect(calls.slice(first,first+4)).toEqual(['rebuild','tile-0','tile-1','text']);
    await d.render({...text,footer:'new caption'},'DIAGRAM',image);expect(bridge.updateImageRawData).toHaveBeenCalledTimes(2);expect(d.rebuildCount).toBe(1);
    await d.render(text,'DIAGRAM',{...image,diagram_id:'other'});expect(d.rebuildCount).toBe(1);expect(bridge.updateImageRawData).toHaveBeenCalledTimes(4);
    await d.render(text,'TEXT');await d.render({...text,main:'page 2'});expect(d.rebuildCount).toBe(2);expect(bridge.rebuildPageContainer).toHaveBeenCalledTimes(2);
  });
  it.each(['imageToGray4Failed','sendFailed','imageSizeInvalid','imageException'])('surfaces %s for controller fallback',async failure=>{
    const d=new LensDisplay({createStartUpPageContainer:async()=>0,textContainerUpgrade:async()=>true,rebuildPageContainer:async()=>true,updateImageRawData:async()=>failure as never});
    await d.render({header:'',main:'',footer:''});const image=await Promise.resolve(tilesFor('test'));
    await expect(d.render({header:'',main:'',footer:'caption'},'DIAGRAM',image)).rejects.toBeInstanceOf(DiagramRenderError);
  });
  it('shows loading until bytes arrive without another rebuild',async()=>{
    const bridge={createStartUpPageContainer:vi.fn(async()=>0),textContainerUpgrade:vi.fn(async()=>true),rebuildPageContainer:vi.fn(async()=>true),updateImageRawData:vi.fn(async()=> 'success' as const)};
    const d=new LensDisplay(bridge);await d.render({header:'',main:'',footer:''});await d.render({header:'Diagram',main:'',footer:'loading diagram'},'DIAGRAM');
    expect(d.rebuildCount).toBe(1);expect(bridge.updateImageRawData).not.toHaveBeenCalled();
    const image=await Promise.resolve(tilesFor('test'));await d.render({header:'Diagram',main:'',footer:'caption'},'DIAGRAM',image);
    expect(d.rebuildCount).toBe(1);expect(bridge.updateImageRawData).toHaveBeenCalledTimes(2);
  });
  it('renders all new screens within 450 chars, including warnings/checkpoints',()=>{
    const assignment=taskFixture(1000);assignment.walkthrough.index=2;
    for(const screen of ['CALIBRATE','PAIRING','TASK_READY','STEP','STEP_DETAILS','DIAGRAM','TASK_DONE'] as const){
      const s={...initialState('new'),screen,walkthrough:assignment.walkthrough,pages:['Body'],pairing:{pair_code:'4F7K',claimed:false,worker_name:null}};
      const text=renderScreen(s);expect(Object.values(text).join('').length).toBeLessThanOrEqual(450);
      Object.values(text).forEach(value=>expect(sanitizeForG2(value)).toBe(value));
      if(screen==='STEP')expect(text.main).toContain('> All four');
    }
  });
  it('routes diagram footer input and head gestures',()=>{
    expect(gestureFromEvent({textEvent:{containerID:3,eventType:1}},3)).toBe('UP');
    expect(gestureFromEvent({textEvent:{containerID:2,eventType:1}},3)).toBeNull();
    expect(gestureFromEvent('NOD')).toBe('NOD');expect(gestureFromEvent('SHAKE')).toBe('SHAKE');
  });
});
