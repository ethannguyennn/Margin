// Canned relay responses + a fake mic, so Part 1 can drive real screens with no
// relay, no glasses and no network. Enabled by VITE_MOCK=1.
import type { AskRequest, AskResponse, Assignment, Command, DiagramImage, Pairing, ProgressEvent, Step } from '../types.ts';
import { SAMPLE_RATE } from '../settings.ts';
import { mockDiagramImage } from './tiles.ts';

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

// v2 voice commands (BUILD-PLAN-V2 §3). Whole-utterance match, exactly like the relay's
// parse_command, so "what's the next step's torque" stays a question.
const COMMAND_PHRASES: Record<Command, string[]> = {
  next: ['next', 'done', 'next step', 'finished', 'complete'],
  back: ['back', 'previous', 'go back'],
  repeat: ['repeat', 'say that again'],
  details: ['details', 'more', 'read it'],
  diagram: ['diagram', 'show diagram', 'picture', 'show me'],
  pause: ['pause', 'stop task'],
  resume: ['resume', 'continue'],
  exit: ['exit', 'close margin'],
};

export function mockCommandFor(transcript: string): Command | null {
  const t = transcript.toLowerCase().replace(/[^a-z' ]+/g, ' ').replace(/\s+/g, ' ').trim();
  for (const [cmd, phrases] of Object.entries(COMMAND_PHRASES) as [Command, string[]][]) if (phrases.includes(t)) return cmd;
  return null;
}

function commandResponse(transcript: string, command: Command): AskResponse {
  return base({
    trace_id: `mock-cmd-${command}`,
    transcript,
    intent: 'command',
    outcome: 'command',
    command,
    verified: false,
    latency_ms: { stt: 380, embed: 0, retrieve: 0, generate: 0, verify: 0, total: 400 },
  });
}

/** Substring triggers, first match wins - order matters. */
const TRIGGERS: Array<[string[], AskResponse]> = [
  [['log deviation', 'deviation'], LOGGED],
  [['boom'], ERROR],
  [['guide me', 'walk me through', 'walkthrough'], WALKTHROUGH],
  [['how tight', 'torque', 'm5'], TORQUE],
  [['clean', 'disinfect'], CLEAN],
];

export function mockResponseFor(transcript: string): AskResponse {
  const cmd = mockCommandFor(transcript);
  if (cmd) return commandResponse(transcript, cmd);
  const t = transcript.toLowerCase();
  for (const [keys, res] of TRIGGERS) if (keys.some((k) => t.includes(k))) return res;
  return { ...NOT_FOUND, transcript: transcript || NOT_FOUND.transcript };
}

/** What mock "STT" hears on the next audio asks, in order (dev buttons, tests). Empty = torque. */
const heard: string[] = [];
export function queueMockTranscripts(...texts: string[]): void {
  heard.push(...texts);
}

export async function mockAsk(req: AskRequest): Promise<AskResponse> {
  // Audio requests have no client-side transcript: use the queued one, else the torque question.
  const said = req.text ?? heard.shift();
  const res = said ? mockResponseFor(said) : TORQUE;
  // Commands take the relay's fast path (no retrieval, no LLM), so they come back quicker.
  await sleep(res.outcome === 'command' ? MOCK_DELAY_MS / 3 : MOCK_DELAY_MS);
  return res;
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

let endpointTimer: ReturnType<typeof setTimeout> | null = null;
let mockNoSpeech = false;
type MockEndpoint = 'speech_end' | 'no_speech' | 'cap';
/** The mock endpoint: what fires and when after startCapture. Default speech_end at 1.5 s. */
let endpointPlan: { reason: MockEndpoint; ms: number } = { reason: 'speech_end', ms: 1500 };
export function setMockEndpoint(reason: MockEndpoint, ms = reason === 'no_speech' ? 3000 : 1500): void {
  endpointPlan = { reason, ms };
}

/** 1.5 s level ramp so Part 1's input meter animates with no hardware. */
export async function mockStartCapture(
  onLevel: (rms01: number) => void,
  onEndpoint?: (reason: MockEndpoint) => void,
): Promise<void> {
  if (capturing) return;
  capturing = true;
  mockNoSpeech = false;
  const plan = endpointPlan;
  let t = 0;
  rampTimer = setInterval(() => {
    t += 100;
    onLevel(plan.reason === 'no_speech' ? 0.02 : 0.15 + 0.75 * Math.sin(((t % 1500) / 1500) * Math.PI));
  }, 100);
  endpointTimer = setTimeout(() => {
    if (rampTimer) clearInterval(rampTimer);
    rampTimer = null;
    mockNoSpeech = plan.reason === 'no_speech';
    console.info(`[audio] mock endpoint ${plan.reason}`);
    onEndpoint?.(plan.reason);
  }, plan.ms);
}

export async function mockStopCapture(): Promise<{ data_b64: string; sample_rate: 16000 }> {
  if (rampTimer) clearInterval(rampTimer);
  if (endpointTimer) clearTimeout(endpointTimer);
  rampTimer = endpointTimer = null;
  capturing = false;
  return { data_b64: mockNoSpeech ? '' : 'bW9jay1wY20=', sample_rate: SAMPLE_RATE };
}

export function mockIsCapturing(): boolean {
  return capturing;
}

// --- v2: pairing, assignment, progress, diagrams ----------------------------
let pairedAt = 0;
const CLAIM_AFTER_MS = 5000;
const DEVICE = { device_id: 'dev-mock-1', device_token: 'mock-device-token', pair_code: '4F7K' };

function pairing(): Pairing {
  const claimed = pairedAt > 0 && Date.now() - pairedAt >= CLAIM_AFTER_MS;
  return { ...DEVICE, claimed, worker_name: claimed ? 'Bay 3' : null };
}

/** Code 4F7K; the "supervisor" claims it 5 s after the first pair(). */
export async function mockPair(): Promise<Pairing> {
  await sleep(MOCK_DELAY_MS / 3);
  if (!pairedAt) pairedAt = Date.now();
  return pairing();
}

export async function mockPairingStatus(): Promise<Pairing> {
  await sleep(MOCK_DELAY_MS / 3);
  return pairing();
}

const TASK_STEPS: Step[] = [
  {
    step_id: 'SOP-114:C:5.1',
    label: 'Step 1 of 5',
    glance: 'Lock out power at the panel',
    body: 'Open the service panel, move the disconnect to OFF and apply your personal lock and tag.',
    warning: 'Verify zero energy before touching any terminal',
    checkpoint: null,
    diagram: null,
  },
  {
    step_id: 'SOP-114:C:5.3',
    label: 'Step 2 of 5',
    glance: 'Remove the guard',
    body: 'Back out the six M4 guard screws and set the guard aside. Keep the screws in the tray.',
    warning: null,
    checkpoint: null,
    diagram: { diagram_id: 'dg-sop114-guard', width: 576, height: 144, alt: 'Guard, six M4 screws' },
  },
  {
    step_id: 'SOP-114:C:5.4',
    label: 'Step 3 of 5',
    glance: 'Seat the bracket',
    body: 'Align the bracket dowels with the frame holes and press until both dowels bottom out.',
    warning: null,
    checkpoint: 'Both dowels bottomed out, no gap at the frame',
    diagram: { diagram_id: 'dg-sop114-bracket', width: 576, height: 144, alt: 'Bracket, M5 torque order 1-4' },
  },
  {
    step_id: 'SOP-114:C:5.5',
    label: 'Step 4 of 5',
    glance: 'Torque M5 to 4 N-m',
    body: 'Torque all four M5 screws to 4 N-m in a diagonal pattern, then re-check the first.',
    warning: null,
    checkpoint: null,
    diagram: null,
  },
  {
    step_id: 'SOP-114:C:5.7',
    label: 'Step 5 of 5',
    glance: 'Refit guard, restore power',
    body: 'Refit the guard, torque the six M4 screws to 1.5 N-m, remove your lock and close the disconnect.',
    warning: null,
    checkpoint: null,
    diagram: null,
  },
];

const ASSIGNMENT: Assignment = {
  assignment_id: 'asg-mock-1',
  assigned_at: '2026-10-17T09:00:00Z',
  walkthrough: {
    doc_id: 'SOP-114',
    revision: 'C',
    title: 'Bracket replacement',
    total: TASK_STEPS.length,
    index: 0,
    steps: TASK_STEPS,
    assignment_id: 'asg-mock-1',
  },
};

/** Every progress event the mock "relay" accepted, de-duplicated like the real one. */
export const mockProgressLog: ProgressEvent[] = [];

/** The task, once the device is claimed, until it is reported task_completed. */
export async function mockNextAssignment(): Promise<Assignment | null> {
  await sleep(MOCK_DELAY_MS / 3);
  if (!pairing().claimed) return null;
  const done = mockProgressLog.some((e) => e.assignment_id === ASSIGNMENT.assignment_id && e.kind === 'task_completed');
  return done ? null : structuredClone(ASSIGNMENT);
}

export async function mockPostProgress(events: ProgressEvent[]): Promise<{ accepted: number }> {
  await sleep(MOCK_DELAY_MS / 3);
  const key = (e: ProgressEvent) => `${e.assignment_id}|${e.step_id}|${e.kind}|${e.ts}`;
  const seen = new Set(mockProgressLog.map(key));
  for (const e of events) {
    if (seen.has(key(e))) continue;
    seen.add(key(e));
    mockProgressLog.push(e);
  }
  return { accepted: events.length };
}

export async function mockGetDiagram(diagram_id: string): Promise<DiagramImage | null> {
  await sleep(MOCK_DELAY_MS);
  return mockDiagramImage(diagram_id);
}

/** Test seam: forget pairing, progress, queued transcripts and the endpoint plan. */
export function resetMockV2(): void {
  pairedAt = 0;
  mockProgressLog.length = 0;
  heard.length = 0;
  endpointPlan = { reason: 'speech_end', ms: 1500 };
}

export const fixtures = { TORQUE, WALKTHROUGH, CLEAN, NOT_FOUND, LOGGED, ERROR, ASSIGNMENT };
