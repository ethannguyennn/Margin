// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { answerGraphic, stepGraphic } from '../src/ui/sop-graphics';
import { createLayout, LensDisplay } from '../src/ui/layout';
import { renderScreen } from '../src/ui/screens';
import { initialState, transition } from '../src/state';
import { AnswerDetail } from '../src/phone/components/AnswerDetail';
import { UI_FIXTURES } from '../src/ui/fixtures';
import type { AskResponse, Step } from '../src/types';
afterEach(cleanup);
const body='Purge the steam wand for 2 seconds before and after every use.';
const step: Step={step_id:'SOP-220:C:4.4',label:'4.4',glance:'Purge the steam wand.',body,graphic_id:'milk-steaming'};
const answer: AskResponse={...UI_FIXTURES.answer,body,glance:step.glance,graphic_id:step.graphic_id,
  citations:[{chunk_id:step.step_id,doc_id:'SOP-220',revision:'C',section:'4.4',quote:body}]};

it('binds explicit Gemini and old-relay images to cited revision and source',()=>{
  expect(answerGraphic(answer)?.id).toBe('milk-steaming');
  expect(answerGraphic({...answer,graphic_id:undefined})?.id).toBe('milk-steaming');
  expect(answerGraphic({...answer,graphic_id:null})).toBeNull();
  expect(answerGraphic({...answer,graphic_id:'https://unsafe.test/image'})).toBeNull();
  expect(answerGraphic({...answer,graphic_id:'allergen-binder'})).toBeNull();
  expect(answerGraphic({...answer,verified:false})).toBeNull();
  expect(stepGraphic({...step,step_id:'SOP-220:X:4.4'})).toBeNull();
  expect(stepGraphic({...step,body:'Different content.'})).toBeNull();
});
it('shows the same accessible figure alongside phone text',()=>{
  render(<AnswerDetail res={answer} pinnedStepId={null} onUseStep={()=>{}}/>);
  expect(screen.getByRole('img',{name:/milk pitcher, wand and tip/i})).toBeTruthy();
  expect(screen.getByText(/Synthetic training reference/)).toBeTruthy();
});
it('keeps images with answer and v2 step details, preserving pagination and warning copy',()=>{
  let state=transition({...initialState('test'),screen:'THINKING'}, {type:'RESPONSE',response:{...answer,body:body.repeat(5)},now:1}).state;
  expect(renderScreen(state).graphic_id).toBe('milk-steaming');
  expect(state.pages.every(p=>p.length<=130)).toBe(true);
  const wt={doc_id:'SOP-220',revision:'C',title:'Espresso',steps:[step],total:1,index:0};
  state={...state,screen:'STEP',walkthrough:wt,response:null};
  expect(renderScreen(state).graphic_id).toBe('milk-steaming');
  state=transition(state,{type:'PRESS'}).state;
  expect(state.screen).toBe('STEP_DETAILS');
  expect(renderScreen(state).graphic_id).toBe('milk-steaming');
  state={...state,screen:'STEP',walkthrough:{...wt,steps:[{...step,warning:'A'.repeat(80),checkpoint:'B'.repeat(60)}]}};
  expect(renderScreen(state).graphic_id).toBeUndefined();
  expect(renderScreen(state).main).toContain('A'.repeat(80));
  expect(renderScreen(state).main).toContain('B'.repeat(60));
});
function bridge(){return {createStartUpPageContainer:vi.fn(async()=>0),textContainerUpgrade:vi.fn(async()=>true),
  rebuildPageContainer:vi.fn(async()=>true),updateImageRawData:vi.fn(async()=> 'success' as never)};}
it('preserves existing two-tile diagrams and adds a bounded accompanying image layout',()=>{
  const text={header:'SOP-220',main:body,footer:'source'};
  const reference=createLayout(text,'REFERENCE');
  expect(reference.containerTotalNum).toBe(4);
  expect(reference.imageObject).toHaveLength(1);
  expect(reference.textObject!.find(c=>c.containerID===2)?.width).toBe(280);
  expect(reference.textObject!.filter(c=>c.isEventCapture===1)).toHaveLength(1);
  const diagram=createLayout(text,'DIAGRAM');
  expect(diagram.imageObject).toHaveLength(2);
  expect(diagram.textObject!.find(c=>c.containerID===2)).toBeUndefined();
});
it('sends encoded PNG references after the text, and a fresh page for a different picture',async()=>{
  const native=bridge(), display=new LensDisplay(native), text={header:'',main:body,footer:''};
  await display.render(text);
  await display.render({...text,graphic_id:'milk-steaming'});
  await display.render({...text,main:'Next',graphic_id:'milk-steaming'});
  expect(native.updateImageRawData).toHaveBeenCalledTimes(1);
  const png=(native.updateImageRawData.mock.calls[0] as unknown as [{imageData:Uint8Array}])[0].imageData;
  expect(Array.from(png.slice(0,8))).toEqual([137,80,78,71,13,10,26,10]); // the host decodes PNG; raw pixels only work in the simulator
  expect(png.length).toBeLessThan(4096);
  await display.render({...text,graphic_id:'espresso-shot'});
  expect(native.updateImageRawData).toHaveBeenCalledTimes(2);
  expect(native.rebuildPageContainer).toHaveBeenCalledTimes(2); // new picture = new page, never a stale one beside new text
  expect(native.rebuildPageContainer.mock.invocationCallOrder[1]).toBeLessThan(native.updateImageRawData.mock.invocationCallOrder[1]);
  await display.render(text,'DIAGRAM',{diagram_id:'existing',tiles:[{slot:0,width:288,height:144,image:'existing-png'}]});
  await display.render(text);
  expect(native.rebuildPageContainer).toHaveBeenCalledTimes(4);
});
it('keeps the instruction when the reference upload fails, and retries on a later visit',async()=>{
  const native=bridge(); native.updateImageRawData.mockResolvedValue('sendFailed' as never);
  const display=new LensDisplay(native), step={header:'',main:body,footer:'',graphic_id:'milk-steaming'};
  await display.render({header:'',main:'Ready',footer:''});
  await display.render(step);
  const last=(native.rebuildPageContainer.mock.calls.at(-1) as unknown as [{containerTotalNum:number;imageObject?:unknown[];textObject:{containerID:number;content:string;width:number}[]}])[0];
  expect(last.containerTotalNum).toBe(3);
  expect(last.imageObject ?? []).toHaveLength(0);
  expect(last.textObject.find(c=>c.containerID===2)).toMatchObject({content:body,width:576});
  await display.render({...step,footer:'notice'});
  expect(native.updateImageRawData).toHaveBeenCalledTimes(1); // same screen: no retry loop
  await display.render({header:'',main:'Ready',footer:''});
  await display.render(step);
  expect(native.updateImageRawData).toHaveBeenCalledTimes(2);
});
