// Frozen contract, client side. The lens app owns these shapes (app/src/types.ts);
// the companion imports them instead of redeclaring them, exactly as the relay's
// schemas.py asks ("Import these shapes; never redefine them").
export type {
  AskRequest,
  AskResponse,
  Citation,
  Intent,
  Latency,
  Outcome,
  Step,
  Walkthrough,
} from '../../app/src/types';

// The contract defines these server-side; app/src/types.ts only mirrors the /v1/ask
// half, so they are declared once here for the companion's own routes.
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
