import type { ReactNode } from 'react';
import type { Outcome } from '../contract';

/** Status marks carry no colour: solid, outlined, or dimmed. */
export type Tone = 'plain' | 'solid' | 'dim';

export function Pill({ tone = 'plain', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`chip${tone === 'plain' ? '' : ` ${tone}`}`}>{children}</span>;
}

const OUTCOME_TONE: Record<Outcome, Tone> = {
  answered: 'plain',
  not_found: 'dim',
  logged: 'plain',
  clarify: 'dim',
  error: 'dim',
};

const OUTCOME_LABEL: Record<Outcome, string> = {
  answered: 'Answered',
  not_found: 'Not in approved SOPs',
  logged: 'Deviation logged',
  clarify: 'Asking to clarify',
  error: 'Error',
};

export function outcomeTone(outcome: string): Tone {
  return OUTCOME_TONE[outcome as Outcome] ?? 'dim';
}

export function OutcomePill({ outcome }: { outcome: Outcome }) {
  return <Pill tone={outcomeTone(outcome)}>{OUTCOME_LABEL[outcome] ?? outcome}</Pill>;
}

/** The relay never answers unverified; the filled mark is what the phone shows when it does. */
export function VerifiedPill({ verified }: { verified: boolean }) {
  return <Pill tone={verified ? 'solid' : 'dim'}>{verified ? 'Verified · cited' : 'Unverified'}</Pill>;
}
