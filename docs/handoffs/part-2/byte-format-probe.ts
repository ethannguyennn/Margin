// SCRATCH - day-one byte-format + IMU probe. Never committed.
import { waitForEvenAppBridge, CreateStartUpPageContainer, TextContainerProperty, ImageContainerProperty, ImuReportPace, OsEventTypeList } from '@evenrealities/even_hub_sdk';
const W = 288, H = 144;
const log = (m: string) => { console.info('[probe] ' + m); (document.getElementById('out')!).textContent += '\n' + m; };
// Test pattern, values 0..15:
//  rows 0-47   : 16 bands of 18 px, value = band index (gradient, left dark -> right bright)
//  rows 48-95  : even x = 15, odd x = 0 (nibble order)
//  rows 96-143 : x < 72 lit 15, else 0 (left/right flip marker)
function level(x: number, y: number): number {
  if (y < 48) return Math.min(15, Math.floor(x / 18));
  if (y < 96) return x % 2 === 0 ? 15 : 0;
  return x < 72 ? 15 : 0;
}
const levels = new Uint8Array(W * H);
for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) levels[y * W + x] = level(x, y);
const raw8x17 = Array.from(levels, (v) => v << 4); // round 2: high nibble only
const raw8x1 = Array.from(levels, (v) => (v << 4) | (15 - v)); // round 2: hi=v, lo=15-v
const packed: number[] = [];
for (let i = 0; i < levels.length; i += 2) packed.push((levels[i] << 4) | levels[i + 1]); // high nibble = left pixel
async function png(): Promise<number[]> {
  const c = document.createElement('canvas'); c.width = W; c.height = H;
  const ctx = c.getContext('2d')!; const img = ctx.createImageData(W, H);
  for (let i = 0; i < levels.length; i++) { const g = levels[i] * 17; img.data.set([g, g, g, 255], i * 4); }
  ctx.putImageData(img, 0, 0);
  const blob: Blob = await new Promise((r) => c.toBlob((b) => r(b!), 'image/png'));
  return Array.from(new Uint8Array(await blob.arrayBuffer()));
}
const b = await waitForEvenAppBridge();
const tiles = [
  { id: 2, name: 'png', x: 0, y: 0 }, { id: 3, name: 'raw8x17', x: 288, y: 0 },
  { id: 4, name: 'packed4', x: 0, y: 144 }, { id: 5, name: 'raw8x1', x: 288, y: 144 },
];
const r = await b.createStartUpPageContainer(new CreateStartUpPageContainer({
  containerTotalNum: 5,
  textObject: [new TextContainerProperty({ containerID: 1, containerName: 'cap', xPosition: 556, yPosition: 268, width: 20, height: 20, isEventCapture: 1, content: ' ', borderWidth: 0, borderColor: 0, borderRadius: 0, paddingLength: 0 })],
  imageObject: tiles.map((t) => new ImageContainerProperty({ containerID: t.id, containerName: t.name, xPosition: t.x, yPosition: t.y, width: W, height: H })),
}));
log('startup=' + r);
const data: Record<string, number[]> = { png: await png(), raw8x17, packed4: packed, raw8x1 };
const only = new URLSearchParams(location.search).get('only');
for (const t of tiles) {
  if (only && only !== t.name) continue;
  const t0 = performance.now();
  let res: unknown;
  try { res = await b.updateImageRawData({ containerID: t.id, containerName: t.name, imageData: data[t.name] }); } catch (e) { res = 'threw ' + (e as Error).message; }
  log(`fmt=${t.name} bytes=${data[t.name].length} result=${String(res)} ms=${(performance.now() - t0).toFixed(0)}`);
}
// IMU: does the simulator emit IMU_DATA_REPORT at all?
for (const pace of [ImuReportPace.P100, ImuReportPace.P500, ImuReportPace.P1000]) {
  let n = 0; let sample: unknown = null; const t0 = performance.now();
  const un = b.onEvenHubEvent((e) => { if (e.sysEvent?.eventType === OsEventTypeList.IMU_DATA_REPORT || e.sysEvent?.imuData) { n++; sample ??= e.sysEvent?.imuData; } });
  let ok: unknown; try { ok = await b.imuControl(true, pace); } catch (e) { ok = 'threw ' + (e as Error).message; }
  await new Promise((res) => setTimeout(res, 3000));
  await b.imuControl(false); un();
  log(`imu pace=${pace} imuControl=${String(ok)} events=${n} in ${((performance.now() - t0) / 1000).toFixed(1)}s sample=${JSON.stringify(sample)}`);
}
log('DONE');
