// TEMPORARY -- Part 1 owns this file. Pasted from README-PART-2-APP-IO.md section 6
// so the app/io modules compile standalone. On `git merge scaffold-app`:
//   git checkout --theirs app/src/types.ts
export type Intent = 'question' | 'walkthrough' | 'deviation' | 'repeat' | 'unknown';
export type Outcome = 'answered' | 'not_found' | 'logged' | 'clarify' | 'error';

export interface Citation { chunk_id: string; doc_id: string; revision: string; section: string; quote: string; }
export interface Step { step_id: string; label: string; glance: string; body: string; }
export interface Walkthrough { doc_id: string; revision: string; title: string; total: number; index: number; steps: Step[]; }
export interface Latency { stt: number; embed: number; retrieve: number; generate: number; verify: number; total: number; }

export interface AskRequest {
  session_id: string;
  audio?: { format: 'pcm_s16le'; sample_rate: 16000; channels: 1; data_b64: string };
  text?: string | null;
  revision?: string | null;
  context?: { doc_id: string | null; step_id: string | null };
}

export interface AskResponse {
  trace_id: string;
  transcript: string;
  intent: Intent;
  outcome: Outcome;
  glance: string;
  body: string;
  source: string;
  citations: Citation[];
  verified: boolean;
  walkthrough: Walkthrough | null;
  latency_ms: Latency;
  error?: { code: string; message: string };
}
