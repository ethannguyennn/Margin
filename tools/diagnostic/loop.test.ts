// Worker loop through the real app modules against a live relay. Copy into app/tests to run:
//   SPECS_DIAG_RELAY=http://127.0.0.1:8090 npx vitest run tests/zz-diagnostic-loop.test.ts
// IMU: the double-nod fixture re-expressed as the G2's gravity vector drives the real Detector;
// audio: Windows SAPI speech from tools/diagnostic/wav (16 kHz s16le mono).
import { test } from 'vitest';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const RELAY = process.env.SPECS_DIAG_RELAY!;
process.env.VITE_RELAY_ORIGIN = RELAY;
process.env.VITE_MOCK = '0';
process.env.VITE_ASK_TIMEOUT_MS = process.env.SPECS_DIAG_TIMEOUT_MS ?? '50000';
const PACE_MS = Number(process.env.SPECS_DIAG_PACE_MS ?? 6000); // Gemini free tier: 15 req/min

const { ask } = await import('../src/api/client.ts');
const { LensController, initialState } = await import('../src/state.ts');
const { renderScreen } = await import('../src/ui/screens.ts');
const { graphicPng, getGraphic, graphicAsset } = await import('../src/ui/sop-graphics.ts');
const { Detector, DEFAULT_PARAMS } = await import('../src/motion/gestures.ts');
const { fixtureSamples } = await import('../src/motion/imu.ts');

const WAV = new URL(process.env.SPECS_DIAG_WAV ?? '../../tools/diagnostic/wav/', import.meta.url);
const SAY = { open: 2, next: 10, done: 11, back: 12, whatsNext: 13, fridge: 16, tooWarm: 17, sanitizer: 19, scoop: 21 } as const;

function pcm(n: number): string {
  const b = readFileSync(new URL(`${n}.wav`, WAV));
  let o = 12;
  while (b.toString('ascii', o, o + 4) !== 'data') o += 8 + b.readUInt32LE(o + 4);
  return b.subarray(o + 8, o + 8 + b.readUInt32LE(o + 4)).toString('base64');
}

type S = { t: number; x: number; y: number; z: number };
const fixture = (name: string): S[] => fixtureSamples(JSON.parse(readFileSync(new URL(`./motion/fixtures/${name}`, import.meta.url), 'utf8')));
const gravity = (s: S[]) => s.map(v => { const p = v.x * Math.PI / 180, r = v.z * Math.PI / 180;
  return { t: v.t, x: Math.sin(r) * Math.cos(p), y: Math.sin(p), z: Math.cos(p) * Math.cos(r) }; });
const nodStream = gravity(fixture('double-nod.synthetic.json'));
const workStream = gravity(fixture('bench-work.synthetic.json'));

test('worker loop: voice-open SOP, step through, clarify, images, IMU nods', { timeout: 300000 }, async () => {
  const log: string[] = [];
  let endpoint: (() => void) | undefined, next = -1, clock = 0, cursor = 0;
  const detector = new Detector(DEFAULT_PARAMS);
  const frames: { screen: string; header: string; main: string; footer: string; graphic_id?: string }[] = [];
  const asks: { said: number; ms: number; outcome: string; transcript: string }[] = [];
  const c = new LensController({ ...initialState(crypto.randomUUID()), screen: 'IDLE', privacySeen: true, calibrated: true,
    pairing: { pair_code: 'X', claimed: true, worker_name: 'diag' } }, {
    startCapture: async (_l, onEndpoint) => { endpoint = () => onEndpoint?.('speech_end'); },
    stopCapture: async () => ({ data_b64: next >= 0 ? pcm(next) : '', sample_rate: 16000 as const }),
    ask: async (req, opts) => { const t = Date.now(); const r = await ask(req, opts);
      asks.push({ said: next, ms: Date.now() - t, outcome: r.outcome, transcript: r.transcript }); return r; },
    render: async s => { const f = renderScreen(s, 0); frames.push({ screen: s.screen, ...f }); },
    persist: async () => {}, exit: async () => {}, now: Date.now, onError: e => log.push(String(e)),
  });
  await c.start();
  const screen = () => c.state.screen;
  const settle = async (want: string[], ms = 60000) => {
    const t = Date.now();
    while (!want.includes(screen()) && Date.now() - t < ms) await new Promise(r => setTimeout(r, 50));
    assert.ok(want.includes(screen()), `expected ${want} got ${screen()} ${log.join(' | ')}`);
  };
  /** Feed IMU samples until the Detector reports a NOD, dispatching it like main.ts does. */
  const nod = () => {
    for (let i = 0; i < nodStream.length * 2; i++, cursor++) {
      const s = nodStream[cursor % nodStream.length];
      clock += 20;
      const g = detector.push({ ...s, t: clock });
      if (g) { c.dispatch({ type: g }); return g; }
    }
    throw new Error('no nod detected');
  };
  /** Bench work between asks: must never trigger the mic. */
  const work = (n = 1500) => { let false_ = 0;
    for (let i = 0; i < n; i++) { clock += 20; if (detector.push({ ...workStream[i % workStream.length], t: clock })) false_++; }
    return false_; };
  const speak = async (n: number, want: string[]) => {
    await new Promise(r => setTimeout(r, PACE_MS));
    endpoint = undefined;
    assert.equal(nod(), 'NOD');
    assert.equal(screen(), 'LISTENING', 'a double nod opens the mic');
    while (!endpoint) await new Promise(r => setTimeout(r, 10)); // capture starts on a later tick
    next = n; endpoint();            // VAD endpoint after the utterance
    await settle(want);
  };
  const step = () => c.state.walkthrough!.index;
  const frame = () => frames.at(-1)!;

  // 1. Open a procedure by voice, not by its name.
  await speak(SAY.open, ['STEP']);
  const w = c.state.walkthrough!;
  console.info(`[diag] opened ${w.doc_id} "${w.title}" ${w.total} steps; first: ${w.steps[0].label} ${w.steps[0].glance}`);
  assert.equal(w.doc_id, 'SOP-210');
  const start = step();
  console.info(`[diag] starts at ${w.steps[start].label} ${w.steps[start].glance}`);

  // 2. Step through by voice and by swipe; images follow the step.
  const falseNods = work();
  await speak(SAY.next, ['STEP']); assert.equal(step(), start + 1, '"next"');
  await speak(SAY.done, ['STEP']); assert.equal(step(), start + 2, '"okay I\'m done with that one"');
  await speak(SAY.back, ['STEP']); assert.equal(step(), start + 1, '"go back"');
  await speak(SAY.whatsNext, ['STEP']); assert.equal(step(), start + 2, '"what\'s next"');
  const target = w.steps.findIndex(s => s.label === '3.2');
  while (step() < target) c.dispatch({ type: 'DOWN' });
  while (step() > target) c.dispatch({ type: 'UP' });
  assert.equal(frame().screen, 'STEP');
  console.info(`[diag] on step ${step() + 1}/${w.total}: ${frame().main.replace(/\n+/g, ' / ')}`);

  // 3. Confused on step 3.2: ask, read the answer, return to the same step.
  await speak(SAY.fridge, ['ANSWER_GLANCE', 'NOT_FOUND', 'ERROR']);
  const a1 = { screen: screen(), ...frame() };
  c.dispatch({ type: 'DISMISS' });
  assert.equal(screen(), 'STEP'); assert.equal(step(), target, 'answer returns to the same step');
  await speak(SAY.tooWarm, ['ANSWER_GLANCE', 'NOT_FOUND', 'ERROR']);
  const a2 = { screen: screen(), ...frame() };
  c.dispatch({ type: 'DISMISS' });
  console.info(`[diag] clarify "fridge temp" -> ${a1.screen}: ${a1.main} [${a1.footer}]`);
  console.info(`[diag] clarify "too warm"   -> ${a2.screen}: ${a2.main} [${a2.footer}]`);

  // 4. Images: every illustrated step renders its graphic on STEP or STEP_DETAILS, with lens + phone assets.
  const shown: string[] = [];
  for (let i = step(); i < w.total; i++) {
    const s = w.steps[i];
    if (s.graphic_id) {
      c.dispatch({ type: 'PRESS' }); // details
      const id = frames.filter(f => f.screen === 'STEP' || f.screen === 'STEP_DETAILS').slice(-2).map(f => f.graphic_id).find(Boolean);
      assert.equal(id, s.graphic_id, `step ${s.label} shows ${s.graphic_id}`);
      const png = await graphicPng(id!);
      assert.deepEqual([...png.subarray(0, 4)], [0x89, 0x50, 0x4e, 0x47], 'lens PNG');
      assert.ok(graphicAsset(getGraphic(id)!), 'phone asset');
      shown.push(`${s.label}:${id}`);
      c.dispatch({ type: 'DOUBLE_PRESS' }); // back to step
    }
    if (i < w.total - 1) c.dispatch({ type: 'DOWN' });
  }
  console.info(`[diag] step images shown: ${shown.join(', ')}`);
  assert.ok(shown.length > 0);

  // 5. A question whose answer carries a picture.
  await speak(SAY.sanitizer, ['ANSWER_GLANCE', 'NOT_FOUND', 'ERROR']);
  const a3 = { screen: screen(), ...frame() };
  c.dispatch({ type: 'DISMISS' });
  console.info(`[diag] "sanitizer" -> ${a3.screen}: ${a3.main} graphic=${a3.graphic_id}`);

  // 6. Finish the task.
  c.dispatch({ type: 'DOWN' });
  assert.equal(screen(), 'TASK_DONE');

  console.info(`[diag] bench-work false nods: ${falseNods}`);
  console.info('[diag] asks: ' + asks.map(a => `#${a.said} ${a.outcome} ${a.ms}ms "${a.transcript}"`).join('\n  '));
  assert.equal(falseNods, 0);
  assert.equal(a1.screen, 'ANSWER_GLANCE');
  assert.equal(a2.screen, 'ANSWER_GLANCE', 'follow-up on the current step');
  assert.equal(a3.screen, 'ANSWER_GLANCE', 'glance-only answer');
  await c.dispose();
});

// v3 (BUILD-PLAN-V3 M8 against a live relay). Opt in with SPECS_DIAG_V3=1 once Part 2's relay sends
// `clarify` and `scope` and Part 3's client.ts passes `clarify` through. Typed asks (the phone path),
// so it needs no extra recordings.
test.skipIf(process.env.SPECS_DIAG_V3 !== '1')('v3 loop: scoped walkthrough, clarify, reply back on the step', { timeout: 300000 }, async () => {
  const c = new LensController({ ...initialState(crypto.randomUUID()), screen: 'IDLE', privacySeen: true, calibrated: true,
    pairing: { pair_code: 'X', claimed: true, worker_name: 'diag' } }, {
    startCapture: async () => {}, stopCapture: async () => ({ data_b64: '', sample_rate: 16000 as const }),
    ask: (req, opts) => ask(req, opts), render: async () => {}, persist: async () => {}, exit: async () => {},
    now: Date.now, onError: () => {},
  });
  await c.start();
  const settle = async (want: string[]) => {
    const t = Date.now();
    while (!want.includes(c.state.screen) && Date.now() - t < 60000) await new Promise(r => setTimeout(r, 50));
    assert.ok(want.includes(c.state.screen), `expected ${want} got ${c.state.screen}`);
  };
  const say = async (text: string, want: string[]) => {
    await new Promise(r => setTimeout(r, PACE_MS));
    assert.ok(c.askText(text), `lens refused "${text}" on ${c.state.screen}`);
    await settle(want);
  };
  await say('walk me through making a cappuccino', ['STEP']);
  const w = c.state.walkthrough!, scope = w.scope!;
  assert.ok(scope, 'spoken walkthrough is scoped');
  assert.equal(w.steps[scope.start].label, '3.2'); assert.equal(w.steps[scope.end - 1].label, '3.4');
  const at = w.index;
  await say('how many pumps of syrup?', ['CLARIFY']);
  const options = c.state.response!.clarify!.options;
  console.info(`[diag v3] clarify ${c.state.response!.clarify!.prompt} ${options.join(' / ')}`);
  await say(options[1], ['ANSWER_GLANCE']);
  console.info(`[diag v3] reply "${options[1]}" -> ${renderScreen(c.state, 0).main}`);
  c.dispatch({ type: 'DISMISS' });
  assert.equal(c.state.screen, 'STEP'); assert.equal(c.state.walkthrough!.index, at);
  for (let i = at; i < scope.end - 1; i++) c.dispatch({ type: 'DOWN' });
  c.dispatch({ type: 'DOWN' });
  assert.equal(c.state.screen, 'TASK_DONE'); assert.equal(renderScreen(c.state, 0).main, `${scope.end - scope.start}/${scope.end - scope.start} steps`);
  await c.dispose();
});
