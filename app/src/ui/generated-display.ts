import type { DisplaySpec } from '../types';
import { sanitizeForG2 } from './glyphs';
import { paginate } from './paginate';

/** Older relays omit this field. Unknown or malformed layouts use the ordinary answer. */
export function parseDisplay(value: unknown): DisplaySpec | null {
  if (!value || typeof value !== 'object') return null;
  const d = value as DisplaySpec;
  if (!['answer', 'checklist', 'warning'].includes(d.kind) || !Array.isArray(d.items) ||
      d.items.length < 1 || d.items.length > 4 ||
      !d.items.every(item => typeof item === 'string' && sanitizeForG2(item).trim().length > 0 &&
        sanitizeForG2(item).length <= 180)) return null;
  return { kind: d.kind, items: d.items.map(item => sanitizeForG2(item).trim().replace(/\s+/g, ' ')) };
}

export function displayPages(display: DisplaySpec | null, budget: number): string[] {
  return display && display.kind !== 'answer' ? display.items.flatMap(item =>
    paginate(`${display.kind === 'checklist' ? '□ ' : ''}${item}`, budget)) : [];
}
