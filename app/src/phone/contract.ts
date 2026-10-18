// Frozen contract, client side. The lens app owns these shapes (src/types.ts); the
// phone screen imports them instead of redeclaring them.
export type {
  AskRequest,
  AskResponse,
  Citation,
  Intent,
  Latency,
  Outcome,
  Step,
  Walkthrough,
} from '../types';

// The contract defines these server-side; types.ts only mirrors the /v1/ask half,
// so they are declared once here for the phone's own routes.
export interface Procedure {
  doc_id: string;
  title: string;
  revision: string;
  status: 'effective' | 'superseded' | 'draft';
}

export interface DeviationResult {
  deviation_id: string;
  notified: boolean;
}

export interface Health {
  ok: boolean;
  mock: boolean;
  db: string;
  version: string;
}
