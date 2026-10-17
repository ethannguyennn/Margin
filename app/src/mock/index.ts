// Canned relay responses + a fake mic, so Part 1 can drive real screens with no
// relay, no glasses and no network. Enabled by VITE_MOCK=1.
import type { AskRequest, AskResponse, Step } from '../types.ts';
import { SAMPLE_RATE } from '../settings.ts';

/** Artificial ask latency so THINKING is actually visible. Set to 0 in tests. */
export let MOCK_DELAY_MS = 900;
export function setMockDelayMs(ms: number): void {
  MOCK_DELAY_MS = ms;
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

function base(partial: Partial<AskResponse>): AskResponse {
  return {
    trace_id: 'mock-trace',
    transcript: '',
    intent: 'question',
    outcome: 'answered',
    glance: '',
    body: '',
    source: '',
    citations: [],
    verified: false,
    walkthrough: null,
    latency_ms: { stt: 420, embed: 90, retrieve: 160, generate: 980, verify: 30, total: 1680 },
    ...partial,
  };
}

const TORQUE: AskResponse = base({
  transcript: 'how tight is the m5 on the mounting bracket',
  outcome: 'answered',
  glance: 'Step 4.2: torque M5 to 4 N-m',
  body:
    'Torque all four M5 bracket screws to 4 N-m in a diagonal pattern. Re-check the ' +
    'first screw after the fourth is seated. Do not exceed 4.4 N-m; the bracket boss ' +
    'strips above that.',
  source: 'SOP-114 Sec 4.2 rev C',
  citations: [
    {
      chunk_id: 'SOP-114:C:4.2',
      doc_id: 'SOP-114',
      revision: 'C',
      section: '4.2',
      quote: 'Torque all four M5 bracket screws to 4 N-m',
    },
  ],
  verified: true,
});

const WALKTHROUGH_STEPS: Step[] = [
  {
    step_id: 'SOP-114:C:5.1',
    label: 'Step 1 of 7',
    glance: 'Lock out power at the panel',
    body: 'Open the service panel, move the disconnect to OFF and apply your personal lock and tag.',
  },
  {
    step_id: 'SOP-114:C:5.2',
    label: 'Step 2 of 7',
    glance: 'Verify zero energy',
    body: 'Probe L1-L2, L2-L3 and L1-L3. All three must read under 2 V before you continue.',
  },
  {
    step_id: 'SOP-114:C:5.3',
    label: 'Step 3 of 7',
    glance: 'Remove the guard',
    body: 'Back out the six M4 guard screws and set the guard aside. Keep the screws in the tray.',
  },
  {
    step_id: 'SOP-114:C:5.4',
    label: 'Step 4 of 7',
    glance: 'Seat the bracket',
    body: 'Align the bracket dowels with the frame holes and press until both dowels bottom out.',
  },
  {
    step_id: 'SOP-114:C:5.5',
    label: 'Step 5 of 7',
    glance: 'Torque M5 to 4 N-m',
    body: 'Torque all four M5 screws to 4 N-m in a diagonal pattern, then re-check the first.',
  },
  {
    step_id: 'SOP-114:C:5.6',
    label: 'Step 6 of 7',
    glance: 'Refit the guard',
    body: 'Refit the guard and torque the six M4 screws to 1.5 N-m. The guard must not rock.',
  },
  {
    step_id: 'SOP-114:C:5.7',
    label: 'Step 7 of 7',
    glance: 'Restore power and sign off',
    body: 'Remove your lock, close the disconnect and record the torque values on the job card.',
  },
];

const WALKTHROUGH: AskResponse = base({
  transcript: 'walk me through the bracket replacement',
  intent: 'walkthrough',
  outcome: 'answered',
  glance: 'Bracket replacement, 7 steps',
  body: 'Bracket replacement, 7 steps. Swipe to advance.',
  source: 'SOP-114 Sec 5 rev C',
  citations: [
    {
      chunk_id: 'SOP-114:C:5',
      doc_id: 'SOP-114',
      revision: 'C',
      section: '5',
      quote: 'Bracket replacement procedure',
    },
  ],
  verified: true,
  walkthrough: {
    doc_id: 'SOP-114',
    revision: 'C',
    title: 'Bracket replacement',
    total: 7,
    index: 0,
    steps: WALKTHROUGH_STEPS,
  },
});

// Body is long on purpose: it must paginate to 2 pages on the lens.
const CLEAN: AskResponse = base({
  transcript: 'how do i clean the optical window',
  outcome: 'answered',
  glance: 'Sec 3.4: IPA wipe, 30 s dwell',
  body:
    'Wear nitrile gloves. Power down the sensor head and wait 60 seconds for the lamp to cool. ' +
    'Flood a lint-free wipe with 70% isopropyl alcohol - do not spray the window directly, the ' +
    'solvent wicks behind the gasket and fogs the inner face. Wipe in one direction from the ' +
    'centre outward, never in circles. Let the surface dwell wet for 30 seconds so protein ' +
    'residue lifts, then dry with a second unused wipe before the alcohol flashes off, or you ' +
    'will leave a ring. Inspect at a glancing angle under the inspection lamp. If any haze ' +
    'remains, repeat once; two passes is the limit before the window must be logged for ' +
    'replacement. Dispose of both wipes in the solvent waste bin, not the general waste. ' +
    'Record the clean on the sensor log with your badge number and the date.',
  source: 'SOP-120 Sec 3.4 rev B',
  citations: [
    {
      chunk_id: 'SOP-120:B:3.4',
      doc_id: 'SOP-120',
      revision: 'B',
      section: '3.4',
      quote: 'Let the surface dwell wet for 30 seconds',
    },
  ],
  verified: true,
});

const NOT_FOUND: AskResponse = base({
  transcript: 'where is the good coffee',
  intent: 'unknown',
  outcome: 'not_found',
  glance: 'Not in approved SOPs',
  body: 'No matching procedure. Try rephrasing or ask your supervisor.',
  citations: [],
  verified: false,
});

const LOGGED: AskResponse = base({
  transcript: 'log deviation bracket arrived pre-drilled',
  intent: 'deviation',
  outcome: 'logged',
  glance: 'Deviation logged',
  body: 'Deviation recorded against SOP-114 Sec 4.2 and sent to your supervisor.',
  source: 'SOP-114 Sec 4.2 rev C',
  citations: [],
  verified: false,
});

const ERROR: AskResponse = base({
  transcript: 'boom',
  intent: 'unknown',
  outcome: 'error',
  glance: '',
  body: '',
  citations: [],
  verified: false,
  error: { code: 'llm_timeout', message: 'The model did not answer in time.' },
});

/** Substring triggers, first match wins - order matters. */
const TRIGGERS: Array<[string[], AskResponse]> = [
  [['log deviation', 'deviation'], LOGGED],
  [['boom'], ERROR],
  [['guide me', 'walk me through', 'walkthrough'], WALKTHROUGH],
  [['how tight', 'torque', 'm5'], TORQUE],
  [['clean', 'disinfect'], CLEAN],
];

export function mockResponseFor(transcript: string): AskResponse {
  const t = transcript.toLowerCase();
  for (const [keys, res] of TRIGGERS) if (keys.some((k) => t.includes(k))) return res;
  return { ...NOT_FOUND, transcript: transcript || NOT_FOUND.transcript };
}

export async function mockAsk(req: AskRequest): Promise<AskResponse> {
  await sleep(MOCK_DELAY_MS);
  // Audio requests have no client-side transcript; pretend STT heard the torque question.
  return req.text ? mockResponseFor(req.text) : TORQUE;
}

export async function mockHealth() {
  return { ok: true, mock: true, db: 'mock', version: 'mock' };
}

export async function mockLogDeviation() {
  await sleep(MOCK_DELAY_MS);
  return { deviation_id: 'dev-mock-1', notified: true };
}

// --- fake mic -------------------------------------------------------------
let rampTimer: ReturnType<typeof setInterval> | null = null;
let capturing = false;

/** 1.5 s level ramp so Part 1's input meter animates with no hardware. */
export async function mockStartCapture(onLevel: (rms01: number) => void): Promise<void> {
  if (capturing) return;
  capturing = true;
  let t = 0;
  rampTimer = setInterval(() => {
    t += 100;
    onLevel(0.15 + 0.75 * Math.sin(((t % 1500) / 1500) * Math.PI));
  }, 100);
}

export async function mockStopCapture(): Promise<{ data_b64: string; sample_rate: 16000 }> {
  if (rampTimer) clearInterval(rampTimer);
  rampTimer = null;
  capturing = false;
  return { data_b64: 'bW9jay1wY20=', sample_rate: SAMPLE_RATE };
}

export function mockIsCapturing(): boolean {
  return capturing;
}

export const fixtures = { TORQUE, WALKTHROUGH, CLEAN, NOT_FOUND, LOGGED, ERROR };
