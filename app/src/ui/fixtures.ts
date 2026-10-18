// Synthetic UI fixtures only. Part 2 owns the app's actual mock/audio/API modules.
import type { AskResponse, Assignment, Command, DiagramImage, Pairing, ProgressEvent } from '../types';

const answered: AskResponse = {
  trace_id: 'fixture-answer', transcript: 'What torque for the M5 screws?', intent: 'question',
  outcome: 'answered', glance: 'Torque M5 bracket screws to 4 N-m.',
  body: 'Torque all four M5 bracket screws to 4 N-m in a star pattern. Use a calibrated wrench. Confirm the bracket is seated on both dowel pins before tightening. Mark each screw after checking torque. This is a synthetic training procedure.',
  source: 'SOP-114 Sec 4.2 rev C', verified: true,
  citations: [{ chunk_id: 'synthetic-114-42', doc_id: 'SOP-114', revision: 'C', section: '4.2', quote: 'Torque all four M5 bracket screws to 4 N-m in a star pattern.' }],
  walkthrough: null, latency_ms: { stt: 0, embed: 0, retrieve: 0, generate: 0, verify: 0, total: 0 },
};
export const FIXTURE_NAMES = ['answer', 'not_found', 'error', 'walkthrough', 'logged'] as const;
export const UI_FIXTURES: Readonly<Record<typeof FIXTURE_NAMES[number], AskResponse>> = {
  answer: answered,
  not_found: { ...answered, trace_id: 'fixture-not-found', outcome: 'not_found', verified: false,
    glance: 'Not in approved SOPs', body: 'No matching procedure. Try rephrasing or ask your supervisor.', citations: [] },
  error: { ...answered, trace_id: 'fixture-error', outcome: 'error', verified: false, glance: '', body: '', citations: [],
    error: { code: 'FIXTURE_ERROR', message: 'Synthetic relay error' } },
  walkthrough: { ...answered, trace_id: 'fixture-walkthrough', intent: 'walkthrough',
    walkthrough: { doc_id: 'SOP-114', revision: 'C', title: 'Synthetic bracket assembly', total: 3, index: 0,
      steps: [
        { step_id: '1', label: 'Seat', glance: 'Seat bracket on dowel pins.', body: 'Seat the bracket squarely on both dowel pins. Check alignment before inserting screws.' },
        { step_id: '2', label: 'Torque', glance: 'Torque M5 screws to 4 N-m.', body: 'Torque all four M5 screws to 4 N-m in a star pattern using a calibrated wrench. ' + 'Check each screw and mark it only after confirming torque. '.repeat(5) },
        { step_id: '3', label: 'Inspect', glance: 'Inspect and record completion.', body: 'Inspect bracket seating and torque marks. Record completion in the synthetic training log.' },
      ] } },
  logged: { ...answered, trace_id: 'fixture-logged', intent: 'deviation', outcome: 'logged', glance: 'Deviation logged.', body: 'Synthetic training deviation recorded.' },
};

// Temporary UI-only PNG fixture; image format must be adopted/confirmed by Part 2.
const fixtureTiles: DiagramImage["tiles"] = [{"slot": 0, "width": 288, "height": 144, "image": "iVBORw0KGgoAAAANSUhEUgAAASAAAACQCAYAAACoPrZBAAADiklEQVR4nO3Xwa7bOgxF0fz/T/dNAw/6bJfSIaNFYM0CxlKuN9rP5/P5AxASfwDgXPEHAM4VfwDgXPEHAM4VfwDgXPEHAM4VfwDgXH//gDHGvB0BMsbERoCMMbEpDVCD/y8CzQkQECNAQIwAATECBMQIEBAjQECMAAExAgTECBAQc0SAdk/6vDDFw/emdFnkkDsmfV6Y4uF7U7oscsgdkz4vTPHwvSld1vWQbb8Dfo0ADfoO+DUCVLSj69mhMwEq2tH17NCZABXt6Hp26EyAinZ0PTt0JkBFO7qeHToToKIdXc8OnQlQ0Y6uZ4fOBKhoR9ezQ2cCVLSj69mhMwEq2tH17NCZABXt6Hp26EyAinZ0PTt0JkBFO7qeHToToKIdXc8OnQlQ0Y6uZ4fOBKhoR9ezQ2cCVLSj69mhMwEq2tH17NCZAA36Dvg1AjToO+DXHBegHZM+L0zx8L0pXRY55I5JnxemePjelC6LHHLHpM8LUzx8b0qXAYcTICBGgIAYAQJiBAiIESAgRoCAGAECYgQIiBEgIEaAgBgBAmIECIgRICBGgIAYAQJiBAiIESAgRoCAGAECYgQIiBkVIGPMvhEgATImNgIkQMbERoAEyJjYCBDw0wQIiBEgIEaAgBgBAmIECIgRICBGgIAYAQJiBAiIESAgRoCAGAGCl3ZP+ryr7/DG50uXwWi7J33e1Xd44/Oly2C03ZM+7+o7vPH50mUw2o6/919/pwQIXvq/v/eKf+H8+jslQPCSAK2/w4vSZTCaAK2/w4vSZTBaxd+7AAkQvCJA2+9w/Q8CUwjQ9jtc/4PAFAK0/Q7X/yAwhQBtv8P1PwhMIUDb73D9DwJTPInHnXnzHdMJELwkQOvv8KJ0GYwmQOvv8KJ0GYy2Ix6//k4JELwkQOvv8OLsy4JvArT+Di/Oviz4JkDr7/Di7MuCbwK0/g4vzr4s+CZA6+/w4uzLgm9PAnRn3nzHdAIELwnQ+ju8KF0GownQ+ju8KF0Go+2e9HlX3+GNz5cug9F2T/q8q+/wxudLl8Fouyd93tV3eOPzpcuAwwkQECNAQIwAATECBMQIEBAjQECMAAExAgTECBAQI0BAjAABMQIExAgQECNAQIwAATECBMQIEBCzLEDGGPNkBMgYExsBMsbE5p8DBLBQ/AGAc8UfADhX/AGAc8UfADhX/AGAc8UfADhX/AGAc8UfADjUf7AwhuU5Ut/XAAAAAElFTkSuQmCC"}, {"slot": 1, "width": 288, "height": 144, "image": "iVBORw0KGgoAAAANSUhEUgAAASAAAACQCAYAAACoPrZBAAADgElEQVR4nO3XQY7cMAxFQd//0sk28CKxHUqfHBWBWk1DY6rHD8l1XdcvgJD4AwDnij8AcK74AwDnij8AcK74AwDnij8AcK74AwDn+vsHjDHm6wiQMSY2AmSMiU1pgBr8fxFoToCAGAECYgQIiBEgIEaAgBgBAmIECIgRICBGgICYIwK0e9L7whQv35vSwyJL7pj0vjDFy/em9LDIkjsmvS9M8fK9KT2s65Jtfwf8NAJ0vf8X0qTdoTMBugQIUgToEiBIEaCiM7ruDp0JUNEZXXeHzgSo6Iyuu0NnAlR0RtfdoTMBKjqj6+7QmQAVndF1d+hMgG4/fzKTdofOBOgSIEgRoEuAIEWAis7oujt0JkBFZ3TdHToToKIzuu4OnQlQ0Rldd4fOBKjojK67Q2cCVHRG192hMwG6/fzJTNodOhOgS4AgRYAuAYKU4wK0Y9L7whQv35vSwyJL7pj0vjDFy/em9LDIkjsmvS9M8fK9KT0MOJwAATECBMQIEBAjQECMAAExAgTECBAQI0BAjAABMQIExAgQECNAQIwAATECBMQIEBAjQECMAAExAgTECBAQI0BAzKgAGWP2jQAJkDGxESABMiY2AiRAxsRGgIAfTYCAGAECYgQIiBEgIEaAgBgBAmIECIgRICBGgIAYAQJiBAiIESD4aPek9119hw8+X3oYjLZ70vuuvsMHny89DEbbPel9V9/hg8+XHgaj7fh7/+nvlADBRwK0fb+zLwv+9K+/9yfvQ8UZkwkQfCRA6+/wpvQwGE2A1t/hTelhMJoArb/Dm9LDYDQBWn+HN6WHwWgCtP4Ob0oPg9EEaP0d3pQeBqMJ0Po7vCk9DEZ7E48n8+V3TCdA8JEArb/Dm9LDYDQBWn+HN6WHwWgVf+8CJEDwiQBtv8P1XwhMIUDb73D9FwJTCND2O1z/hcAUArT9Dtd/ITCFAG2/w/VfCEwhQNvvcP0XAlPs+Hv/6e+UAMFHArR9v7MvC/60e9L7rr7DB58vPQxG2z3pfVff4YPPlx4Go+2e9L6r7/DB50sPAw4nQECMAAExAgTECBAQI0BAjAABMQIExAgQECNAQIwAATECBMQIEBAjQECMAAExAgTECBAQI0BAzLIAGWPMmxEgY0xsBMgYE5v/DhDAQvEHAM4VfwDgXPEHAM4VfwDgXPEHAM4VfwDgXPEHAM4VfwDgUL8B7tAfW8S6UQgAAAAASUVORK5CYII="}];

export function taskFixture(now=Date.now()): Assignment {
  const steps=structuredClone(UI_FIXTURES.walkthrough.walkthrough!.steps);
  steps.push({step_id:'4',label:'Check',glance:'Check the torque marks.',body:'Check all four torque marks on the synthetic bracket.'},
    {step_id:'5',label:'Record',glance:'Record completion.',body:'Record completion of the synthetic training procedure.'});
  steps[0].warning='Disconnect the training rig before assembly.';
  steps[2].checkpoint='All four torque marks must be visible.';
  for(const index of [1,2]) steps[index].diagram={diagram_id:`fixture-step-${index+1}`,width:576,height:144,alt:'Synthetic bracket torque order 1-4'};
  return {assignment_id:'fixture-assignment-114',assigned_at:new Date(now).toISOString(),walkthrough:{doc_id:'SOP-114',revision:'C',title:'Synthetic bracket assembly',total:5,index:0,steps,assignment_id:'fixture-assignment-114'}};
}
/** TEMPORARY SECTION-6 UI STUB. Delete this adapter + fixtureTiles when Part 2's v2 mocks land. */
export function createLocalV2FixturePorts(readUtterance:()=>string,scenario='m1') {
  let callback:((g:'NOD'|'SHAKE')=>void)|null=null,calibrated=false,capturing=false;
  let timer:ReturnType<typeof setTimeout>|undefined,utterance='',assigned=false;
  const born=Date.now();
  const pairing:Pairing={device_id:'fixture-device',device_token:'fixture-only-not-a-credential',pair_code:'4F7K',claimed:false,worker_name:null};
  const mapped:Record<string,Command>={next:'next',done:'next','next step':'next',finished:'next',complete:'next',back:'back',previous:'back','go back':'back',repeat:'repeat','say that again':'repeat',details:'details',more:'details','read it':'details',diagram:'diagram','show diagram':'diagram',picture:'diagram','show me':'diagram',pause:'pause','stop task':'pause',resume:'resume',continue:'resume',exit:'exit','close margin':'exit'};
  return {
    audio:{
      async startCapture(onLevel:(v:number)=>void,onEndpoint?:(reason:'speech_end'|'no_speech'|'cap')=>void){capturing=true;utterance=readUtterance().trim().toLowerCase();onLevel(0.5);clearTimeout(timer);timer=setTimeout(()=>onEndpoint?.(utterance==='silence'?'no_speech':'speech_end'),1500);},
      async stopCapture(){clearTimeout(timer);capturing=false;return {data_b64:utterance==='silence'?'':btoa('synthetic-ui-fixture'),sample_rate:16000 as const};},
      isCapturing:()=>capturing,
    },
    api:{
      async pair(){return {...pairing};},async pairingStatus(){return {...pairing,claimed:Date.now()-born>=5000,worker_name:'Synthetic worker'};},
      async nextAssignment(){if(scenario!=='m2' || assigned)return null;assigned=true;return taskFixture();},
      reportProgress(ev:ProgressEvent){console.info('[Margin] progress='+JSON.stringify(ev));},
      async getDiagram(id:string):Promise<DiagramImage>{return {diagram_id:id,tiles:structuredClone(fixtureTiles)};},
      async ask():Promise<AskResponse>{
        await new Promise(resolve=>setTimeout(resolve,250));console.info('[Margin] stub-ask='+utterance);
        if(mapped[utterance])return {...structuredClone(UI_FIXTURES.answer),intent:'command',outcome:'command',command:mapped[utterance],verified:false,glance:'',body:'',citations:[],walkthrough:null};
        return structuredClone(UI_FIXTURES[utterance==='not found'?'not_found':utterance==='error'?'error':utterance==='walkthrough'?'walkthrough':utterance==='logged'?'logged':'answer']);
      },
    },
    motion:{
      async startHeadGestures(cb:(g:'NOD'|'SHAKE')=>void){callback=cb;},async stopHeadGestures(){callback=null;},
      async calibrate(onProgress:(done:number,needed:number)=>void){for(let i=1;i<=3;i++){await new Promise(resolve=>setTimeout(resolve,100));onProgress(i,3);}calibrated=true;return {ok:true};},
      isCalibrated:()=>calibrated,simulateGesture(g:'NOD'|'SHAKE'){callback?.(g);},
    },
    obs:{initObs(){},startAsk(){return {finishSpan(_name:string){},end(_outcome:string){}};}},
  };
}
