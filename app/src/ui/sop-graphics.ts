import catalog from '../../../corpus/illustrations.json';
import type { AskResponse, Step } from '../types';
import { sanitizeForG2 } from './glyphs';

const assets = import.meta.glob('../assets/sops/*.png', { eager: true, query: '?url', import: 'default' });
const lens = import.meta.glob<string>('../assets/lens/*.png', { eager: true, query: '?inline', import: 'default' });
export const GRAPHIC_WIDTH = 288;
export const GRAPHIC_HEIGHT = 144;
export const ILLUSTRATED_PAGE_CHARS = 130;
export type SopGraphic = typeof catalog[number];
const text = (value: string) => sanitizeForG2(value).toLowerCase().replace(/\s+/g, ' ').trim();

export function getGraphic(id: unknown): SopGraphic | null {
  return typeof id === 'string' ? catalog.find(graphic => graphic.id === id) ?? null : null;
}

export function graphicAsset(graphic: SopGraphic): string {
  return assets[`../assets/sops/${graphic.file}`] as string;
}

export function answerGraphic(response: AskResponse | null): SopGraphic | null {
  if (response?.outcome !== 'answered' || response.verified !== true) return null;
  // Older relays have no graphic field; their cited source can still identify a local reference.
  const candidates = response.graphic_id === undefined ? catalog : [getGraphic(response.graphic_id)];
  return candidates.find(graphic => graphic?.references.some(ref => response.citations.some(cite =>
    cite.chunk_id === ref.chunk_id && text(cite.quote).includes(text(ref.quote))))) ?? null;
}

export function stepGraphic(step: Step): SopGraphic | null {
  const candidates = step.graphic_id === undefined ? catalog : [getGraphic(step.graphic_id)];
  return candidates.find(graphic => graphic?.references.some(ref => ref.chunk_id === step.step_id &&
    text(step.body).includes(text(ref.quote)))) ?? null;
}

/** The baked lens PNG (scripts/bake-lens-graphics.py), inlined in the bundle. The glasses host
 * decodes encoded images itself; raw pixel buffers only render in the simulator. */
export async function graphicPng(id: string): Promise<Uint8Array> {
  const url = lens[`../assets/lens/${id}.png`];
  if (!getGraphic(id) || !url) throw new Error('Unknown SOP graphic');
  return Uint8Array.from(atob(url.slice(url.indexOf(',') + 1)), c => c.charCodeAt(0));
}
