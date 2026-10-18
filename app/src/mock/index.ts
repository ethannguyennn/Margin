// Canned relay responses + a fake mic, so Part 1 can drive real screens with no
// relay, no glasses and no network. Enabled by VITE_MOCK=1.
import type { AskRequest, AskResponse } from '../types.ts';
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

// Synthetic fixtures mirror the checked-in SOP corpus, including its visual references.
const TORQUE: AskResponse = base({
  "transcript": "how tight is the m5 on the mounting bracket",
  "outcome": "answered",
  "glance": "Step 4.2: torque M5 to 4 N-m",
  "body": "Torque all four M5 bracket screws to 4 N-m in a star pattern using a calibrated torque wrench (see SOP-131). Tighten in the order upper left, lower right, upper right, lower left. Stop at the first click on each screw; do not click twice.",
  "source": "SOP-114 Sec 4.2 rev C",
  "citations": [
    {
      "chunk_id": "SOP-114:C:4.2",
      "doc_id": "SOP-114",
      "revision": "C",
      "section": "4.2",
      "quote": "Torque all four M5 bracket screws to 4 N-m in a star pattern using a calibrated torque wrench (see SOP-131). Tighten in the order upper left, lower right, upper right, lower left. Stop at the first click on each screw; do not click twice."
    }
  ],
  "verified": true,
  "graphic_id": "bracket-fasteners"
});

const WALKTHROUGH: AskResponse = base({
  "transcript": "walk me through mounting bracket assembly",
  "intent": "walkthrough",
  "outcome": "answered",
  "glance": "Mounting bracket assembly, 7 steps",
  "body": "Mounting bracket assembly, 7 steps. Swipe to advance.",
  "source": "SOP-114 Sec 4.1 rev C",
  "citations": [
    {
      "chunk_id": "SOP-114:C:4.1",
      "doc_id": "SOP-114",
      "revision": "C",
      "section": "4.1",
      "quote": "Disconnect power. Confirm the green RECEIVED label from SOP-101. Check the torque wrench under SOP-131. Seat bracket HX2-210 with the arrow toward the outlet. Fit all four washers and start all four M5 screws by hand for 3 full turns. Keep threads dry."
    },
    {
      "chunk_id": "SOP-114:C:4.2",
      "doc_id": "SOP-114",
      "revision": "C",
      "section": "4.2",
      "quote": "Torque all four M5 bracket screws to 4 N-m in a star pattern using a calibrated torque wrench (see SOP-131). Tighten in the order upper left, lower right, upper right, lower left. Stop at the first click on each screw; do not click twice."
    },
    {
      "chunk_id": "SOP-114:C:4.3",
      "doc_id": "SOP-114",
      "revision": "C",
      "section": "4.3",
      "quote": "Check the gap between the bracket foot and housing with a 0.20 mm feeler gauge. The gauge must not enter at any of the four screw positions. If it enters, stop and report the gap under SOP-140; do not add torque."
    },
    {
      "chunk_id": "SOP-114:C:4.4",
      "doc_id": "SOP-114",
      "revision": "C",
      "section": "4.4",
      "quote": "Apply one blue witness line across each screw head and onto the bracket. Each line must be continuous and visible from the front. Do not mark the pump serial label."
    },
    {
      "chunk_id": "SOP-114:C:4.5",
      "doc_id": "SOP-114",
      "revision": "C",
      "section": "4.5",
      "quote": "Measure the clearance between the bracket edge and outlet collar. Accept at least 6 mm clearance. Route the disconnected power lead outside the bracket opening without pinching it."
    },
    {
      "chunk_id": "SOP-114:C:4.6",
      "doc_id": "SOP-114",
      "revision": "C",
      "section": "4.6",
      "quote": "Record the pump serial number, wrench asset number, 4 N-m setting, and assembler initials on assembly form AS-114. Record revision C. Do not record a measured torque when only a wrench setting was used."
    },
    {
      "chunk_id": "SOP-114:C:4.7",
      "doc_id": "SOP-114",
      "revision": "C",
      "section": "4.7",
      "quote": "Confirm all four witness marks and the completed AS-114. Place the pump in the ASSEMBLED tray. Keep power disconnected; this procedure does not authorize a powered run test."
    }
  ],
  "verified": true,
  "walkthrough": {
    "doc_id": "SOP-114",
    "revision": "C",
    "title": "Mounting Bracket Assembly",
    "total": 7,
    "index": 0,
    "steps": [
      {
        "step_id": "SOP-114:C:4.1",
        "label": "4.1",
        "glance": "Prepare and seat the bracket",
        "body": "Disconnect power. Confirm the green RECEIVED label from SOP-101. Check the torque wrench under SOP-131. Seat bracket HX2-210 with the arrow toward the outlet. Fit all four washers and start all four M5 screws by hand for 3 full turns. Keep threads dry.",
        "graphic_id": "bracket-overview"
      },
      {
        "step_id": "SOP-114:C:4.2",
        "label": "4.2",
        "glance": "Fasten the M5 bracket screws",
        "body": "Torque all four M5 bracket screws to 4 N-m in a star pattern using a calibrated torque wrench (see SOP-131). Tighten in the order upper left, lower right, upper right, lower left. Stop at the first click on each screw; do not click twice.",
        "graphic_id": "bracket-fasteners"
      },
      {
        "step_id": "SOP-114:C:4.3",
        "label": "4.3",
        "glance": "Check the bracket gap",
        "body": "Check the gap between the bracket foot and housing with a 0.20 mm feeler gauge. The gauge must not enter at any of the four screw positions. If it enters, stop and report the gap under SOP-140; do not add torque.",
        "graphic_id": "bracket-gap"
      },
      {
        "step_id": "SOP-114:C:4.4",
        "label": "4.4",
        "glance": "Apply witness marks",
        "body": "Apply one blue witness line across each screw head and onto the bracket. Each line must be continuous and visible from the front. Do not mark the pump serial label.",
        "graphic_id": "bracket-fasteners"
      },
      {
        "step_id": "SOP-114:C:4.5",
        "label": "4.5",
        "glance": "Check outlet clearance",
        "body": "Measure the clearance between the bracket edge and outlet collar. Accept at least 6 mm clearance. Route the disconnected power lead outside the bracket opening without pinching it.",
        "graphic_id": "bracket-overview"
      },
      {
        "step_id": "SOP-114:C:4.6",
        "label": "4.6",
        "glance": "Record assembly",
        "body": "Record the pump serial number, wrench asset number, 4 N-m setting, and assembler initials on assembly form AS-114. Record revision C. Do not record a measured torque when only a wrench setting was used.",
        "graphic_id": null
      },
      {
        "step_id": "SOP-114:C:4.7",
        "label": "4.7",
        "glance": "Release to the next station",
        "body": "Confirm all four witness marks and the completed AS-114. Place the pump in the ASSEMBLED tray. Keep power disconnected; this procedure does not authorize a powered run test.",
        "graphic_id": null
      }
    ]
  }
});

const CLEAN: AskResponse = base({
  "transcript": "how do i disinfect the housing",
  "outcome": "answered",
  "glance": "Use a 70 % IPA wipe; keep wet for 60 s",
  "body": "Wipe the external housing with a premixed 70 % isopropyl alcohol wipe. Keep the surface visibly wet for 60 s. Use a fresh wipe if the surface dries before the contact time ends. Do not dilute the premixed wipe.",
  "source": "SOP-120 Sec 4.3 rev B",
  "citations": [
    {
      "chunk_id": "SOP-120:B:4.3",
      "doc_id": "SOP-120",
      "revision": "B",
      "section": "4.3",
      "quote": "Wipe the external housing with a premixed 70 % isopropyl alcohol wipe. Keep the surface visibly wet for 60 s. Use a fresh wipe if the surface dries before the contact time ends. Do not dilute the premixed wipe."
    }
  ],
  "verified": true,
  "graphic_id": "housing-cleaning"
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
