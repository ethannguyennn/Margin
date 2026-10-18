export type Intent = 'question' | 'walkthrough' | 'deviation' | 'repeat' | 'command' | 'unknown';
export type Outcome = 'answered' | 'not_found' | 'logged' | 'clarify' | 'command' | 'error';
export type Command = 'next' | 'back' | 'repeat' | 'details' | 'diagram' | 'pause' | 'resume' | 'exit';

export interface Citation { chunk_id: string; doc_id: string; revision: string; section: string; quote: string; }
export interface Diagram { diagram_id: string; width: number; height: number; alt: string; }
export interface Step {
  step_id: string; label: string; glance: string; body: string;
  warning?: string | null;     // <= 80 chars, ASCII, shown on the step screen
  checkpoint?: string | null;  // <= 60 chars, e.g. "0.20 mm gauge must not enter"
  graphic_id?: string | null;
  diagram?: Diagram | null;    // only approved diagrams are ever sent
}
export interface Walkthrough {
  doc_id: string; revision: string; title: string; total: number; index: number; steps: Step[];
  assignment_id?: string | null;
}
export interface Latency { stt: number; embed: number; retrieve: number; generate: number; verify: number; total: number; }

export interface AskRequest {
  session_id: string;
  audio?: { format: 'pcm_s16le'; sample_rate: 16000; channels: 1; data_b64: string };
  text?: string | null;
  revision?: string | null;
  context?: { doc_id: string | null; step_id: string | null; assignment_id?: string | null };
}

export interface AskResponse {
  trace_id: string; transcript: string; intent: Intent; outcome: Outcome;
  glance: string; body: string; source: string; citations: Citation[]; verified: boolean;
  walkthrough: Walkthrough | null; latency_ms: Latency;
  graphic_id?: string | null;
  command?: Command | null;           // set iff outcome === 'command'
  needs_clarification?: boolean;      // the relay already sends it (TODO.md §4)
  error?: { code: string; message: string };
}

// Device + task routes
export interface Pairing { device_id: string; device_token: string; pair_code: string; claimed: boolean; worker_name: string | null; }
export interface Assignment { assignment_id: string; walkthrough: Walkthrough; assigned_at: string; }
export type ProgressKind = 'task_started' | 'step_started' | 'step_completed' | 'task_paused' | 'task_completed';
export interface ProgressEvent { assignment_id: string; step_id: string | null; kind: ProgressKind; ts: number; }
export interface DiagramImage {
  diagram_id: string;
  tiles: { slot: 0 | 1; width: number; height: number; image: string /* base64, format per §4 */ }[];
}
