// Mock diagram tiles in the proven lens format: 8-bit greyscale PNG, 288x144, pixel
// values on the 16 lens levels (level x 17). No dependencies: the PNG uses stored
// (uncompressed) deflate blocks, so this runs the same in the WebView and in node.
import type { DiagramImage } from '../types.ts';

export const TILE_W = 288;
export const TILE_H = 144;

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});
function crc32(b: Uint8Array): number {
  let c = 0xffffffff;
  for (const x of b) c = CRC_TABLE[(c ^ x) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
const u32 = (n: number) => [(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255];

function chunk(type: string, data: Uint8Array): number[] {
  const td = new Uint8Array([...Array.from(type, (c) => c.charCodeAt(0)), ...data]);
  return [...u32(data.length), ...td, ...u32(crc32(td))];
}

/** levels: row-major 0..15 per pixel. */
export function encodeGreyPng(levels: Uint8Array, w: number, h: number): Uint8Array {
  const raw = new Uint8Array(h * (w + 1)); // filter byte 0 per row
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) raw[y * (w + 1) + 1 + x] = levels[y * w + x] * 17;
  const z: number[] = [0x78, 0x01];
  for (let i = 0; i < raw.length; i += 65535) {
    const n = Math.min(65535, raw.length - i);
    z.push(i + n >= raw.length ? 1 : 0, n & 255, n >> 8, ~n & 255, (~n >> 8) & 255, ...raw.subarray(i, i + n));
  }
  let a = 1;
  let b = 0;
  for (const x of raw) {
    a = (a + x) % 65521;
    b = (b + a) % 65521;
  }
  z.push(...u32(((b << 16) | a) >>> 0));
  return new Uint8Array([
    137, 80, 78, 71, 13, 10, 26, 10,
    ...chunk('IHDR', new Uint8Array([...u32(w), ...u32(h), 8, 0, 0, 0, 0])), // 8-bit greyscale
    ...chunk('IDAT', new Uint8Array(z)),
    ...chunk('IEND', new Uint8Array()),
  ]);
}

/** A 576x144 canvas split into the two 288x144 tiles. */
class Canvas {
  readonly px = new Uint8Array(TILE_W * 2 * TILE_H);
  dot(x: number, y: number, v = 15): void {
    x = Math.round(x);
    y = Math.round(y);
    if (x >= 0 && y >= 0 && x < TILE_W * 2 && y < TILE_H) this.px[y * TILE_W * 2 + x] = v;
  }
  line(x1: number, y1: number, x2: number, y2: number, v = 15): void {
    const n = Math.max(Math.abs(x2 - x1), Math.abs(y2 - y1), 1);
    for (let i = 0; i <= n; i++)
      for (const d of [0, 1]) this.dot(x1 + ((x2 - x1) * i) / n + d, y1 + ((y2 - y1) * i) / n, v); // 2 px stroke
  }
  rect(x: number, y: number, w: number, h: number, v = 15): void {
    this.line(x, y, x + w, y, v);
    this.line(x + w, y, x + w, y + h, v);
    this.line(x + w, y + h, x, y + h, v);
    this.line(x, y + h, x, y, v);
  }
  circle(cx: number, cy: number, r: number, v = 15): void {
    for (let a = 0; a < 360; a += 2) this.dot(cx + r * Math.cos((a * Math.PI) / 180), cy + r * Math.sin((a * Math.PI) / 180), v);
  }
  tile(slot: 0 | 1): Uint8Array {
    const t = new Uint8Array(TILE_W * TILE_H);
    for (let y = 0; y < TILE_H; y++) t.set(this.px.subarray(y * TILE_W * 2 + slot * TILE_W, y * TILE_W * 2 + (slot + 1) * TILE_W), y * TILE_W);
    return t;
  }
}

const b64 = (b: Uint8Array): string => {
  let s = '';
  for (const x of b) s += String.fromCharCode(x);
  return btoa(s); // global in browsers, the Even WebView and Node 16+
};

const DRAW: Record<string, (c: Canvas) => void> = {
  // Guard with its six M4 screws (step 2).
  'dg-sop114-guard': (c) => {
    c.rect(150, 20, 276, 104);
    for (const [x, y] of [[170, 40], [288, 40], [406, 40], [170, 104], [288, 104], [406, 104]]) c.circle(x, y, 8);
  },
  // Bracket: four M5 screws, diagonal torque order 1-2-3-4 with a gradient key (step 3).
  'dg-sop114-bracket': (c) => {
    c.rect(200, 16, 176, 112);
    const holes = [[224, 40], [352, 104], [352, 40], [224, 104]];
    holes.forEach(([x, y], i) => {
      c.circle(x, y, 10);
      for (let k = 0; k <= i; k++) c.dot(x - 3 + k * 2, y, 15); // i+1 pips = order
    });
    c.line(224, 40, 352, 104, 8);
    c.line(352, 40, 224, 104, 8);
    for (let v = 1; v < 16; v++) for (let y = 0; y < 8; y++) c.line(20 + v * 8, 130 + y, 26 + v * 8, 130 + y, v);
  },
};

export const MOCK_DIAGRAM_IDS = Object.keys(DRAW);

export function mockDiagramImage(diagram_id: string): DiagramImage | null {
  const draw = DRAW[diagram_id];
  if (!draw) return null;
  const c = new Canvas();
  draw(c);
  return {
    diagram_id,
    tiles: ([0, 1] as const).map((slot) => ({
      slot,
      width: TILE_W,
      height: TILE_H,
      image: b64(encodeGreyPng(c.tile(slot), TILE_W, TILE_H)),
    })),
  };
}
