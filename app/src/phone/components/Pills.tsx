import type { ReactNode } from 'react';
import type { Outcome } from '../contract';

export type Tone = 'ok' | 'warn' | 'bad' | 'info' | 'muted';

export function Pill({ tone = 'muted', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`pill pill-${tone}`}>{children}</span>;
}

const OUTCOME_TONE: Record<Outcome, Tone> = {
  answered: 'ok',
  not_found: 'warn',
  logged: 'info',
  clarify: 'warn',
  command: 'info',
  error: 'bad',
};

const OUTCOME_LABEL: Record<Outcome, string> = {
  answered: 'Answered',
  not_found: 'Not in approved SOPs',
  logged: 'Deviation logged',
  clarify: 'Asking to clarify',
  command: 'Voice command',
  error: 'Error',
};

export function outcomeTone(outcome: string): Tone {
  return OUTCOME_TONE[outcome as Outcome] ?? 'muted';
}

export function OutcomePill({ outcome }: { outcome: Outcome }) {
  return <span className={`pill pill-${outcomeTone(outcome)} dot-before`}>{OUTCOME_LABEL[outcome] ?? outcome}</span>;
}

/** The relay never answers unverified; this is what the phone shows when it does. */
export function VerifiedPill({ verified }: { verified: boolean }) {
  return (
    <Pill tone={verified ? 'ok' : 'warn'}>
      {verified ? 'Verified · cited' : 'Unverified'}
    </Pill>
  );
}
