import { describe, expect, it } from 'vitest';
import { initialState, transition, restoreSession, serializeSession, timeoutFor, WALKTHROUGH_TTL_MS,
  type Screen, type Gesture } from '../src/state';
import { UI_FIXTURES } from '../src/ui/fixtures';
import { renderScreen } from '../src/ui/screens';

import { stateFor } from './support';

// Every state x gesture, including intentional no-ops. Columns: press, double, up, down, long.
const map: Record<Screen, Screen[]> = {
  PRIVACY: ['CALIBRATE','PRIVACY','PRIVACY','PRIVACY','PRIVACY'],
  IDLE: ['LISTENING','IDLE','IDLE','IDLE','LISTENING'],
  LISTENING: ['THINKING','IDLE','LISTENING','LISTENING','LISTENING'],
  THINKING: ['THINKING','IDLE','THINKING','THINKING','THINKING'],
  ANSWER_GLANCE: ['ANSWER_EXPANDED','IDLE','ANSWER_GLANCE','ANSWER_GLANCE','LISTENING'],
  ANSWER_EXPANDED: ['ANSWER_GLANCE','ANSWER_GLANCE','ANSWER_EXPANDED','ANSWER_EXPANDED','LISTENING'],
  NOT_FOUND: ['LISTENING','IDLE','NOT_FOUND','NOT_FOUND','LISTENING'],
  WALKTHROUGH: ['STEP_DETAILS','IDLE','STEP','STEP','LISTENING'],
  LOGGED: ['IDLE','IDLE','LOGGED','LOGGED','LISTENING'],
  ERROR: ['LISTENING','IDLE','ERROR','ERROR','LISTENING'],
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
      if (timeoutFor(stateFor(screen)) === null) { expect(result.state.screen).toBe(stateFor(screen).screen); expect(result.effects).toEqual([]); }
      else { expect(result.state.screen).toBe('IDLE'); expect(result.effects).toEqual(['CANCEL']); }
    });
    it(`${screen} fails safely`, () => expect(transition(stateFor(screen), { type: 'FAIL' }).state.screen).toBe('ERROR'));
    if (screen !== 'THINKING') it(`${screen} ignores late responses`, () => {
      const state = stateFor(screen);
      expect(transition(state, { type: 'RESPONSE', response: UI_FIXTURES.answer, now: 0 }).state).toBe(state);
    });
  }
});

describe('response trust routing', () => {
  it('shows only the safe quota copy and keeps arbitrary error text off the lens', () => {
    for (const message of ['Busy, try again', 'UNSAFE provider error text']) {
      const response = { ...UI_FIXTURES.error, error: { code: 'llm_timeout', message } };
      const state = transition(stateFor('THINKING'), { type: 'RESPONSE', response, now: 1000 }).state;
      expect(state.response).toBeNull();
      expect(renderScreen(state).main).toBe(message === 'Busy, try again' ? message : 'No verified answer');
    }
  });
  it.each([['answer','ANSWER_GLANCE'],['not_found','NOT_FOUND'],['error','ERROR'],['walkthrough','STEP'],['logged','LOGGED']] as const)('%s -> %s', (fixture, screen) => {
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
  it('shows a verified glance-only answer (empty body) instead of an error', () => {
    const state = transition(stateFor('THINKING'), { type: 'RESPONSE', response: { ...UI_FIXTURES.answer, body: '' }, now: 1000 }).state;
    expect(state.screen).toBe('ANSWER_GLANCE'); expect(state.pages).toEqual([UI_FIXTURES.answer.glance]);
  });
  it('a walkthrough opens at the relay\'s start step, and back still reaches step 1', () => {
    const response = structuredClone(UI_FIXTURES.walkthrough); response.walkthrough!.index = 2;
    let state = transition(stateFor('THINKING'), { type: 'RESPONSE', response, now: 1000 }).state;
    expect(state.screen).toBe('STEP'); expect(state.walkthrough!.index).toBe(2);
    state = transition(transition(state, { type: 'UP' }).state, { type: 'UP' }).state;
    expect(state.walkthrough!.index).toBe(0);
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
    expect(state.screen).toBe('STEP_DETAILS'); expect(state.pages.length).toBeGreaterThan(1);
    state = transition(state, { type: 'DOWN' }).state; expect(state.page).toBe(1);
    state = transition(state, { type: 'UP' }).state; expect(state.page).toBe(0);
    state = transition(state, { type: 'DOUBLE_PRESS' }).state;
    expect(state.screen).toBe('STEP'); expect(state.walkthrough!.index).toBe(1);
    state = transition(state, { type: 'DOWN' }).state; expect(state.walkthrough!.index).toBe(2);
    state = transition(state, { type: 'PRESS' }).state;
    state = transition(state, { type: 'DOUBLE_PRESS' }).state; expect(state.screen).toBe('STEP');
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
    expect(restored.screen).toBe('STEP'); expect(restored.session_id).toBe('session-test');
    expect(restored.privacySeen).toBe(true); expect(restored.micSource).toBe('phone');
    expect(restored.walkthrough).toEqual(state.walkthrough);
    expect(transition(restored, { type: 'PRESS' }).state.screen).toBe('STEP_DETAILS');
  });
  it.each([WALKTHROUGH_TTL_MS, WALKTHROUGH_TTL_MS + 1, -1])('discards stale or future walkthrough at age %i', age => {
    expect(restoreSession(serializeSession(stateFor('WALKTHROUGH')), 1000 + age, 'new').screen).toBe('IDLE');
  });
  it('restores a walkthrough just inside the 30 minute boundary', () => {
    expect(restoreSession(serializeSession(stateFor('WALKTHROUGH')), 1000 + WALKTHROUGH_TTL_MS - 1, 'new').screen).toBe('STEP');
  });
  it('shows privacy once, never marks it seen on exit', () => {
    const fresh = initialState('session');
    expect(restoreSession('', 1000, 'session').screen).toBe('PRIVACY');
    expect(transition(fresh, { type: 'DOUBLE_PRESS' }).state.privacySeen).toBe(false);
    const accepted = transition(fresh, { type: 'PRESS' }).state;
    expect(restoreSession(serializeSession(accepted), 1000, 'new').screen).toBe('IDLE');
  });
  it('discards malformed cached steps while preserving the session and privacy flag', () => {
    const state = stateFor('WALKTHROUGH'); state.walkthrough!.steps[0].body = 'x'.repeat(451);
    const restored = restoreSession(serializeSession(state), 2000, 'replacement');
    expect(restored.screen).toBe('IDLE'); expect(restored.privacySeen).toBe(true);
    expect(restored.session_id).toBe('session-test'); expect(restored.walkthrough).toBeNull();
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

// v2 acceptance: expectations below are the role's gesture table, not derived
// from transition(). v1 assertions above remain except the specified renames.
import { SCREENS, ASSIGNMENT_TTL_MS, type LensState, type Action } from '../src/state';
import { taskFixture } from '../src/ui/fixtures';
function v2State(screen: Screen): LensState {
  const base={...initialState('v2-session'),privacySeen:true,calibrated:true,pairing:{pair_code:'4F7K',claimed:true,worker_name:'Fixture'}};
  const assignment=taskFixture(1000);assignment.walkthrough.index=2;
  const task=transition({...base,screen:'IDLE'}, {type:'ASSIGNMENT',assignment,now:1001}).state;
  const started=transition(task,{type:'NOD'}).state;
  if(['TASK_READY','STEP','STEP_DETAILS','DIAGRAM','TASK_DONE','WALKTHROUGH'].includes(screen))return {...started,screen,
    ...(screen==='TASK_READY'?{screen:'TASK_READY' as const}:{}),pages:['first page','second page'],diagramId:screen==='DIAGRAM'?'fixture-step-3':null};
  if(['ANSWER_GLANCE','ANSWER_EXPANDED'].includes(screen))return {...stateFor(screen),...{calibrated:true,pairing:base.pairing}};
  return {...base,screen};
}
const inputTypes=['PRESS','DOUBLE_PRESS','UP','DOWN','LONG_PRESS','NOD','SHAKE','ENDPOINT','TIMEOUT'] as const;
const v2Map:Record<Screen,Screen[]>={
  PRIVACY:['CALIBRATE','PRIVACY','PRIVACY','PRIVACY','PRIVACY','PRIVACY','PRIVACY','PRIVACY','PRIVACY'],
  CALIBRATE:['IDLE','CALIBRATE','CALIBRATE','CALIBRATE','CALIBRATE','CALIBRATE','CALIBRATE','CALIBRATE','CALIBRATE'],
  PAIRING:['PAIRING','PAIRING','PAIRING','PAIRING','PAIRING','PAIRING','PAIRING','PAIRING','PAIRING'],
  IDLE:['LISTENING','IDLE','IDLE','IDLE','LISTENING','LISTENING','IDLE','IDLE','IDLE'],
  TASK_READY:['STEP','IDLE','TASK_READY','TASK_READY','STEP','STEP','TASK_READY','TASK_READY','TASK_READY'],
  STEP:['STEP_DETAILS','IDLE','STEP','DIAGRAM','LISTENING','LISTENING','STEP','STEP','STEP'],
  STEP_DETAILS:['STEP_DETAILS','STEP','STEP_DETAILS','STEP_DETAILS','LISTENING','LISTENING','STEP','STEP_DETAILS','STEP_DETAILS'],
  DIAGRAM:['STEP','STEP','DIAGRAM','DIAGRAM','LISTENING','LISTENING','STEP','DIAGRAM','DIAGRAM'],
  TASK_DONE:['IDLE','IDLE','TASK_DONE','TASK_DONE','LISTENING','LISTENING','IDLE','TASK_DONE','IDLE'],
  LISTENING:['THINKING','IDLE','LISTENING','LISTENING','LISTENING','LISTENING','IDLE','THINKING','IDLE'],
  THINKING:['THINKING','IDLE','THINKING','THINKING','THINKING','THINKING','THINKING','THINKING','IDLE'],
  ANSWER_GLANCE:['ANSWER_EXPANDED','IDLE','ANSWER_GLANCE','ANSWER_GLANCE','LISTENING','LISTENING','IDLE','ANSWER_GLANCE','IDLE'],
  ANSWER_EXPANDED:['ANSWER_GLANCE','ANSWER_GLANCE','ANSWER_EXPANDED','ANSWER_EXPANDED','LISTENING','LISTENING','IDLE','ANSWER_EXPANDED','IDLE'],
  NOT_FOUND:['LISTENING','IDLE','NOT_FOUND','NOT_FOUND','LISTENING','LISTENING','IDLE','NOT_FOUND','IDLE'],
  CLARIFY:['LISTENING','IDLE','CLARIFY','CLARIFY','LISTENING','LISTENING','IDLE','CLARIFY','IDLE'],
  WALKTHROUGH:['STEP_DETAILS','IDLE','STEP','DIAGRAM','LISTENING','LISTENING','WALKTHROUGH','WALKTHROUGH','WALKTHROUGH'],
  LOGGED:['IDLE','IDLE','LOGGED','LOGGED','LISTENING','LISTENING','IDLE','LOGGED','IDLE'],
  ERROR:['LISTENING','IDLE','ERROR','ERROR','LISTENING','LISTENING','IDLE','ERROR','IDLE'],
};
describe('v2 complete screen x input matrix',()=>{
  for(const screen of SCREENS)for(const [column,type] of inputTypes.entries())it(`${screen} + ${type}`,()=>{
    const s=v2State(screen),snapshot=structuredClone(s);
    const value=transition(s,{type});expect(value.state.screen).toBe(v2Map[screen][column]);expect(s).toEqual(snapshot);
  });
  for(const screen of SCREENS)it(`${screen}: payload events are gated`,()=>{
    const s=v2State(screen);
    const events:Action[]=[{type:'ASSIGNMENT',assignment:taskFixture(1000),now:1001},{type:'DIAGRAM_READY',id:'wrong-id'},
      {type:'DIAGRAM_FAILED',id:'wrong-id'},{type:'EMPTY_CAPTURE'},{type:'CALIBRATED',ok:true},
      {type:'CALIBRATION_PROGRESS',done:2,needed:3},{type:'RESPONSE',response:UI_FIXTURES.answer,now:1001}];
    for(const a of events){const before=structuredClone(s);const value=transition(s,a);expect(s).toEqual(before);
      if(a.type==='DIAGRAM_READY' || a.type==='DIAGRAM_FAILED')expect(value.state).toBe(s);
      if(a.type==='RESPONSE' && screen!=='THINKING')expect(value.state).toBe(s);
    }
  });
});

describe('v2 returnTo and trust',()=>{
  for(const screen of SCREENS)it(`NOD origin ${screen} is restored exactly after silence/cancel/answer`,()=>{
    const s=v2State(screen),opened=transition(s,{type:'NOD'});
    if(['PRIVACY','CALIBRATE','PAIRING','LISTENING','THINKING','TASK_READY'].includes(screen))return;
    expect(opened.state.returnTo).toBe(screen);
    expect(transition(opened.state,{type:'SHAKE'}).state).toEqual(s);
    const thinking=transition(opened.state,{type:'ENDPOINT'}).state;
    expect(transition(thinking,{type:'EMPTY_CAPTURE'}).state).toEqual(s);
    for(const fixture of ['answer','not_found','error'] as const){
      const answered=transition(thinking,{type:'RESPONSE',response:UI_FIXTURES[fixture],now:2000}).state;
      expect(transition(answered,{type:'SHAKE'}).state).toEqual(s);
      expect(transition(answered,{type:'TIMEOUT'}).state).toEqual(s);
      if(['STEP','STEP_DETAILS','DIAGRAM','WALKTHROUGH'].includes(screen))expect(timeoutFor(answered)).toBe(20000);
    }
  });
  it('commands act locally and never preserve any response text',()=>{
    for(const name of ['next','back','repeat','details','diagram','pause','resume','exit'] as const){
      const start=v2State('STEP'),thinking=transition(transition(start,{type:'NOD'}).state,{type:'ENDPOINT'}).state;
      const value=transition(thinking,{type:'RESPONSE',now:2000,response:{...UI_FIXTURES.answer,outcome:'command',intent:'command',command:name,verified:false,glance:'UNVERIFIED-MUST-NOT-RENDER',body:'UNVERIFIED-MUST-NOT-RENDER'}});
      expect(JSON.stringify(value.state)).not.toContain('UNVERIFIED-MUST-NOT-RENDER');
      expect(value.state.screen).not.toBe('ANSWER_GLANCE');
    }
  });
  it('rejects an unknown command and every unverified answer',()=>{
    const s={...v2State('THINKING'),returnTo:'IDLE' as const};
    for(const response of [{...UI_FIXTURES.answer,verified:false},{...UI_FIXTURES.answer,outcome:'command' as const,command:'invalid' as never}]){
      expect(transition(s,{type:'RESPONSE',response,now:2000}).state.screen).toBe('ERROR');
    }
  });
  it('does not lose an assignment to an ad-hoc response',()=>{
    const task=v2State('STEP');const thinking=transition(transition(task,{type:'NOD'}).state,{type:'ENDPOINT'}).state;
    const value=transition(thinking,{type:'RESPONSE',response:UI_FIXTURES.answer,now:2000}).state;
    expect(value.assignment_id).toBe(task.assignment_id);expect(value.walkthrough!.index).toBe(2);
  });
  it('shows a fixed no-diagram hint, handles diagram failure, and ignores stale readiness',()=>{
    let s=v2State('STEP');s.walkthrough!.steps[2].diagram=null;
    let thinking=transition(transition(s,{type:'NOD'}).state,{type:'ENDPOINT'}).state;
    s=transition(thinking,{type:'RESPONSE',response:{...UI_FIXTURES.answer,outcome:'command',command:'diagram'},now:2000}).state;
    expect(s.notice).toBe('No diagram for this step');
    s=v2State('DIAGRAM');expect(transition(s,{type:'DIAGRAM_FAILED',id:s.diagramId!}).state.notice).toBe('Diagram unavailable');
    expect(transition(s,{type:'DIAGRAM_READY',id:s.diagramId!}).state.diagramReady).toBe(true);
  });
});

describe('v2 assigned task persistence and progression',()=>{
  it.each([ASSIGNMENT_TTL_MS-1,ASSIGNMENT_TTL_MS,ASSIGNMENT_TTL_MS+1,-1])('restores assigned step only under 12h, age=%i',age=>{
    const s=v2State('STEP');const value=restoreSession(serializeSession(s),1000+age,'replacement');
    expect(value.screen).toBe(age>=0 && age<ASSIGNMENT_TTL_MS?'STEP':'IDLE');
    if(value.screen==='STEP'){expect(value.walkthrough!.index).toBe(2);expect(value.assignment_id).toBe(s.assignment_id);}
  });
  it('keeps tasks on pause, resumes locally, and does not restore completed tasks',()=>{
    const s=v2State('STEP'),paused=transition(s,{type:'DOUBLE_PRESS'}).state;
    expect(paused.screen).toBe('IDLE');expect(paused.walkthrough!.index).toBe(2);
    let state=s;
    for(let i=0;i<3;i++){
      const thinking=transition(transition(state,{type:'NOD'}).state,{type:'ENDPOINT'}).state;
      state=transition(thinking,{type:'RESPONSE',response:{...UI_FIXTURES.answer,outcome:'command',command:'next'},now:2000}).state;
    }
    expect(state.screen).toBe('TASK_DONE');expect(restoreSession(serializeSession(state),3000,'new').screen).toBe('IDLE');
  });
  it('never stores pairing credentials, answer snapshots, or audio',()=>{
    let s=v2State('STEP');s=transition(s,{type:'PAIRED',pairing:{device_id:'private-id',device_token:'private-token',pair_code:'4F7K',claimed:true,worker_name:'Fixture'}}).state;
    const stored=serializeSession(s);expect(stored).not.toContain('private-token');expect(stored).not.toContain('private-id');expect(stored).not.toContain('returnState');expect(stored).not.toContain('audio');
  });
  it('keeps calibration and pairing behind privacy, then restores a task after claiming',()=>{
    let s=initialState('new');s=transition(s,{type:'PAIRED',pairing:{device_id:'x',device_token:'x',pair_code:'4F7K',claimed:false,worker_name:null}}).state;
    expect(s.screen).toBe('PRIVACY');s=transition(s,{type:'PRESS'}).state;expect(s.screen).toBe('CALIBRATE');
    s=transition(s,{type:'CALIBRATED',ok:true}).state;expect(s.screen).toBe('PAIRING');
    s=transition(s,{type:'PAIRED',pairing:{device_id:'x',device_token:'x',pair_code:'4F7K',claimed:true,worker_name:'Fixture'}}).state;expect(s.screen).toBe('IDLE');
  });
});

describe('v2 command progression guards',()=>{
  it('cannot complete or resume an already completed task',()=>{
    const done=v2State('TASK_DONE');
    for(const command of ['next','resume','repeat'] as const){
      const thinking=transition(transition(done,{type:'NOD'}).state,{type:'ENDPOINT'}).state;
      const value=transition(thinking,{type:'RESPONSE',response:{...UI_FIXTURES.answer,outcome:'command',command},now:2000});
      expect(value.state.screen).toBe('TASK_DONE');expect(value.effects).toEqual([]);
    }
  });
  it('resume starts a deferred TASK_READY exactly once',()=>{
    let s=v2State('TASK_READY');s.taskStarted=false;
    s=transition(s,{type:'DOUBLE_PRESS'}).state;
    let thinking=transition(transition(s,{type:'NOD'}).state,{type:'ENDPOINT'}).state;
    const first=transition(thinking,{type:'RESPONSE',response:{...UI_FIXTURES.answer,outcome:'command',command:'resume'},now:2000});
    expect(first.state.screen).toBe('STEP');expect(first.state.taskStarted).toBe(true);
    expect(first.effects.filter(e=>typeof e==='object')).toEqual([{type:'REPORT_PROGRESS',kind:'task_started',step_id:null},{type:'REPORT_PROGRESS',kind:'step_started',step_id:'3'}]);
    thinking=transition(transition(first.state,{type:'NOD'}).state,{type:'ENDPOINT'}).state;
    expect(transition(thinking,{type:'RESPONSE',response:{...UI_FIXTURES.answer,outcome:'command',command:'resume'},now:2001}).effects).toEqual(['PREFETCH_DIAGRAMS']);
  });
  it('a verified ad-hoc walkthrough response cannot replace the assigned task',()=>{
    const original=v2State('STEP');const thinking=transition(transition(original,{type:'NOD'}).state,{type:'ENDPOINT'}).state;
    const value=transition(thinking,{type:'RESPONSE',response:UI_FIXTURES.walkthrough,now:2000});
    expect(value.state.assignment_id).toBe(original.assignment_id);expect(value.state.walkthrough).toEqual(original.walkthrough);expect(value.effects).toEqual(['PREFETCH_DIAGRAMS']);
  });
});

describe('double tap resumes a paused task', () => {
  it('from IDLE after a pause, back on the same step; with nothing paused it still exits', () => {
    const paused = transition(v2State('STEP'), { type: 'DOUBLE_PRESS' }).state;
    expect(paused.screen).toBe('IDLE');
    expect(renderScreen(paused).footer).toBe('double-tap: resume');
    const resumed = transition(paused, { type: 'DOUBLE_PRESS' });
    expect(resumed.state.screen).toBe('STEP'); expect(resumed.state.walkthrough!.index).toBe(2);
    expect(resumed.effects).not.toContain('EXIT');
    expect(transition(initialState('new'), { type: 'DOUBLE_PRESS' }).effects).toEqual(['EXIT']);
  });
  it('a task put off from TASK_READY starts on a double tap, reported once', () => {
    const ready = { ...v2State('TASK_READY'), taskStarted: false };
    const off = transition(ready, { type: 'DOUBLE_PRESS' }).state;
    expect(off.screen).toBe('IDLE');
    const started = transition(off, { type: 'DOUBLE_PRESS' });
    expect(started.state.screen).toBe('STEP'); expect(started.state.taskStarted).toBe(true);
    expect(started.effects.filter((e) => typeof e === 'object' && e.type === 'REPORT_PROGRESS' && e.kind === 'task_started')).toHaveLength(1);
  });
});
