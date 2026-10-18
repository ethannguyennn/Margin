import catalog from '../../../corpus/illustrations.json';
import type { AskResponse, Step } from '../types';
import { sanitizeForG2 } from './glyphs';

const assets = import.meta.glob('../assets/sops/*.png', { eager: true, query: '?url', import: 'default' });
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

/** Decode packaged artwork locally into SDK-supported Gray8; no image service/network call. */
export async function graphicPixels(id: string): Promise<Uint8Array> {
  const graphic = getGraphic(id);
  if (!graphic) throw new Error('Unknown SOP graphic');
  const image = new Image();
  image.src = graphicAsset(graphic);
  await image.decode();
  const canvas = document.createElement('canvas');
  canvas.width = GRAPHIC_WIDTH; canvas.height = GRAPHIC_HEIGHT;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('SOP graphic rendering unavailable');
  ctx.fillStyle = 'black'; ctx.fillRect(0, 0, canvas.width, canvas.height);
  const [x, y, width, height] = graphic.crop;
  const sw = image.naturalWidth * width, sh = image.naturalHeight * height;
  const scale = Math.min(canvas.width / sw, canvas.height / sh);
  ctx.drawImage(image, x * image.naturalWidth, y * image.naturalHeight, sw, sh,
    (canvas.width - sw * scale) / 2, (canvas.height - sh * scale) / 2, sw * scale, sh * scale);
  const rgba = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
  // Suppress low-level texture so the monochrome lens shows crisp reference linework.
  return Uint8Array.from({ length: canvas.width * canvas.height }, (_, index) =>
    0.2126 * rgba[index * 4] + 0.7152 * rgba[index * 4 + 1] + 0.0722 * rgba[index * 4 + 2] >= 64 ? 255 : 0);
}
