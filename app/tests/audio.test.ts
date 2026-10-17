// Run: node --test app/tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';

process.env.VITE_MOCK = '0';

const { startCapture, stopCapture, cancelCapture, isCapturing, setBridge } = await import('../src/audio/capture.ts');
const { MAX_AUDIO_BYTES } = await import('../src/settings.ts');

type Call = [boolean, string | undefined];

/** Stands in for the Even bridge: records audioControl calls, exposes the event cb. */
function fakeBridge(openOk = true) {
  const calls: Call[] = [];
  let cb: ((e: any) => void) | null = null;
  let subscribed = 0;
  const bridge = {
    audioControl: async (isOpen: boolean, source?: string) => {
      calls.push([isOpen, source]);
      return isOpen ? openOk : true;
    },
    onEvenHubEvent: (fn: (e: any) => void) => {
      cb = fn;
      subscribed++;
      return () => {
        cb = null;
        subscribed--;
      };
    },
  };
  setBridge(bridge);
  return {
    calls,
    /** Push one 100 ms chunk of constant-amplitude PCM, as the host does. */
    push(amplitude = 16384, ms = 100) {
      const samples = (16000 * ms) / 1000;
      const buf = new Uint8Array(samples * 2);
      const view = new DataView(buf.buffer);
      for (let i = 0; i < samples; i++) view.setInt16(i * 2, amplitude, true);
      cb?.({ audioEvent: { source: 'glasses', audioPcm: buf } });
    },
    get subscribed() {
      return subscribed;
    },
  };
}

test('push-to-talk: opens the glasses mic, levels out, closes on stop', async () => {
  const hw = fakeBridge();
  const levels: number[] = [];
  await startCapture((l) => levels.push(l));
  assert.deepEqual(hw.calls[0], [true, 'glasses']);
  assert.equal(isCapturing(), true);

  hw.push(16384);
  hw.push(16384);
  assert.equal(levels.length, 2);
  assert.ok(Math.abs(levels[0] - 0.5) < 0.001, `rms was ${levels[0]}`);

  const out = await stopCapture();
  assert.equal(out.sample_rate, 16000);
  assert.equal(Buffer.from(out.data_b64, 'base64').length, 2 * 3200);
  assert.deepEqual(hw.calls.at(-1), [false, undefined]);
  assert.equal(isCapturing(), false);
  assert.equal(hw.subscribed, 0, 'listener must be unsubscribed with the mic');
});

test('8 s cap: a 20 s press sends 8 s and the mic is already closed', async () => {
  const hw = fakeBridge();
  await startCapture(() => {});
  for (let i = 0; i < 200; i++) hw.push(8192); // 20 s
  assert.equal(isCapturing(), false, 'mic must close itself at the cap');
  await new Promise((r) => setTimeout(r, 0)); // the audioControl(false) is dispatched, not awaited
  assert.deepEqual(hw.calls.at(-1), [false, undefined]);
  const out = await stopCapture();
  assert.equal(Buffer.from(out.data_b64, 'base64').length, MAX_AUDIO_BYTES);
});

test('second startCapture while capturing is a no-op, not a second mic open', async () => {
  const hw = fakeBridge();
  await startCapture(() => {});
  await startCapture(() => {});
  assert.equal(hw.calls.filter(([open]) => open).length, 1);
  await cancelCapture();
});

test('double-press cancel drops the audio', async () => {
  const hw = fakeBridge();
  await startCapture(() => {});
  hw.push();
  await cancelCapture();
  assert.equal(isCapturing(), false);
  const out = await stopCapture();
  assert.equal(out.data_b64, '');
});

test('permission denied: clear message, mic not left open, next press still works', async () => {
  const denied = fakeBridge(false);
  await assert.rejects(() => startCapture(() => {}), /permission|unavailable/i);
  assert.equal(isCapturing(), false);
  assert.equal(denied.subscribed, 0);

  const granted = fakeBridge(true);
  await startCapture(() => {});
  assert.equal(isCapturing(), true);
  await cancelCapture();
});

test('chunks arriving after the mic closed are ignored', async () => {
  const hw = fakeBridge();
  await startCapture(() => {});
  await cancelCapture();
  hw.push();
  const out = await stopCapture();
  assert.equal(out.data_b64, '');
});
