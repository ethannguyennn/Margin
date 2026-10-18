// Actual Even Hub simulator + its WebView2 dev controls. No controller/state injection.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const base='http://127.0.0.1:9899',cdp='http://127.0.0.1:9224',url='http://localhost:5176';
const output=new URL('../test-artifacts/v2/',import.meta.url);
await mkdir(output,{recursive:true});
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const binary=createRequire(import.meta.url).resolve(`@evenrealities/sim-${process.platform}-${process.arch}/bin/evenhub-simulator${process.platform==='win32'?'.exe':''}`);
function launch(scenario){return spawn(binary,[`${url}/?scenario=${scenario}`,'--automation-port','9899'],{
  stdio:'inherit',windowsHide:true,env:{...process.env,
    WEBVIEW2_USER_DATA_FOLDER:fileURLToPath(new URL(`webview-${scenario}/`,output)),
    WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS:'--remote-debugging-port=9224'}});}
if(process.argv.includes('--launch')){launch('m1');}else{
  const checks=[],runs=[];
  async function until(fn,label,timeout=10000){const start=Date.now();let last;while(Date.now()-start<timeout){try{last=await fn();if(last)return last;}catch{}await wait(80);}throw new Error('Timed out: '+label+' '+JSON.stringify(last));}
  async function entries(){const r=await fetch(`${base}/api/console`,{signal:AbortSignal.timeout(3000)});return(await r.json()).entries;}
  async function lastScreen(){return(await entries()).filter(e=>e.message.includes('[Margin] rendered screen=')).at(-1)?.message;}
  async function screen(name,step,timeout){await until(async()=>{const line=await lastScreen();return line?.includes('screen='+name+' ') && (step===undefined || line.includes('step='+step+' '));},name+' '+step,timeout);checks.push({screen:name,...(step===undefined?{}:{step})});console.log('PASS',name,step??'');}
  async function touch(action){await fetch(`${base}/api/input`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({action})});await wait(150);}
  async function capture(name){await wait(160);for(const kind of ['glasses','webview']){const r=await fetch(`${base}/api/screenshot/${kind}`,{signal:AbortSignal.timeout(10000)});assert.ok(r.ok);await writeFile(new URL(`${name}-${kind}.png`,output),Buffer.from(await r.arrayBuffer()));}}
  async function connect(){
    const target=await until(async()=>{const targets=await(await fetch(cdp+'/json/list')).json();return targets.find(t=>t.url.startsWith(url));},'CDP app target');
    const ws=new WebSocket(target.webSocketDebuggerUrl),pending=new Map();let id=0;
    await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
    ws.onmessage=event=>{const packet=JSON.parse(event.data);if(packet.id){const p=pending.get(packet.id);pending.delete(packet.id);packet.error?p?.reject(new Error(packet.error.message)):p?.resolve(packet.result);}};
    function send(method,params={}){return new Promise((resolve,reject)=>{const key=++id;pending.set(key,{resolve,reject});ws.send(JSON.stringify({id:key,method,params}));});}
    return {send,close:()=>ws.close(),async evaluate(expression){const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw new Error(JSON.stringify(r.exceptionDetails));return r.result?.value;}};
  }
  async function dev(session,id){await session.evaluate(`document.getElementById(${JSON.stringify(id)}).click()`);}
  async function say(session,text){await session.evaluate(`document.getElementById('dev-utterance').value=${JSON.stringify(text)}`);await dev(session,'dev-nod');await screen('LISTENING');}
  async function setup(){await until(async()=>{const r=await fetch(base+'/api/ping');return r.ok;},'simulator startup');const session=await connect();await until(async()=>!!await lastScreen(),'first screen');
    if((await lastScreen()).includes('screen=PRIVACY ')){await capture('privacy');await touch('click');}
    return session;
  }
  async function stop(child){if(child.exitCode===null)child.kill();await until(async()=>{try{await fetch(base+'/api/ping',{signal:AbortSignal.timeout(300)});return false;}catch{return true;}},'simulator exit',6000);}
  let child,session;
  try{
    // M1 setup may acknowledge privacy. The measured flow uses only the Nod button.
    child=launch('m1');session=await setup();await screen('IDLE');await capture('m1-idle');
    await dev(session,'dev-nod');await screen('LISTENING');await capture('m1-listening');
    await screen('THINKING');await screen('ANSWER_GLANCE');await capture('m1-answer');
    await screen('IDLE',undefined,23000);await capture('m1-dim');
    let log=await entries();assert.equal(log.filter(e=>e.message.includes('[Margin] stub-ask=')).length,1);
    assert.equal(log.filter(e=>e.message.includes('[Margin] layout=')).length,0);
    runs.push({flow:'M1',input:'dev Nod button only after setup',taps:0,rebuilds:0});
    await writeFile(new URL('m1-console.json',output),JSON.stringify(log,null,2));
    session.close();await stop(child);
    child=launch('m2');session=await setup();await screen('TASK_READY',0,14000);await capture('m2-task-ready');
    await dev(session,'dev-nod');await screen('STEP',0);await capture('m2-step-1');
    await say(session,'next');await screen('STEP',1);
    await say(session,'next');await screen('STEP',2);await capture('m2-step-3');
    await say(session,'show diagram');await screen('DIAGRAM',2);
    await until(async()=> (await entries()).filter(e=>e.message.includes('tile=') && e.message.includes('status=success')).length===2,'two rendered tiles');
    await capture('m2-diagram');await dev(session,'dev-shake');await screen('STEP',2);await capture('m2-return-step-3');
    log=await entries();const progress=log.filter(e=>e.message.includes('[Margin] progress=')).map(e=>JSON.parse(e.message.split('progress=')[1]));
    assert.deepEqual(progress.map(e=>[e.kind,e.step_id]),[['task_started',null],['step_started','1'],['step_completed','1'],['step_started','2'],['step_completed','2'],['step_started','3']]);
    assert.ok(progress.every((e,i)=>!i || e.ts>progress[i-1].ts));
    assert.equal(log.filter(e=>e.message.includes('[Margin] layout=')).length,2);
    runs.push({flow:'M2',progress:progress.map(({kind,step_id})=>({kind,step_id})),tiles:2,rebuilds:2,input:'dev Nod/Shake; synthetic command fixtures'});
    for(const [utterance,answer] of [['question','ANSWER_GLANCE'],['not found','NOT_FOUND'],['error','ERROR']]){
      await say(session,utterance);await screen(answer,2);await capture('step-question-'+answer.toLowerCase());await dev(session,'dev-shake');await screen('STEP',2);
    }
    // v1 tap fallback and native root exit. Pause retains the assigned step.
    await touch('double_click');await screen('IDLE',2);await touch('double_click');
    await until(async()=> (await entries()).some(e=>e.message.includes('native exit accepted')),'native root exit');await capture('root-exit');
    const beforeReload=(await entries()).at(-1)?.id??0;
    await session.send('Page.reload');
    await until(async()=>{const recent=(await entries()).filter(e=>e.id>beforeReload);return recent.some(e=>e.message.includes('rendered screen=STEP ') && e.message.includes('step=2 '));},'cold-start restore STEP 3',14000);
    await capture('cold-start-step-3');checks.push({screen:'STEP',step:2,coldStart:true});
    log=await entries();const errors=log.filter(e=>e.level==='error' || /\[uncaught\]|\[unhandledrejection\]/.test(e.message));assert.deepEqual(errors,[]);
    await writeFile(new URL('m2-console.json',output),JSON.stringify(log,null,2));
    await writeFile(new URL('results.json',output),JSON.stringify({checks,runs,rootExit:true,coldStartStep:3,hardware:'not yet tested on hardware',integration:'temporary UI mocks; not Part 2 IMU replay or live relay',errors},null,2));
    console.log('PASS M1, M2, returnTo, native exit, cold start; '+checks.length+' screen assertions.');
  }finally{session?.close();if(child)await stop(child);}
}
