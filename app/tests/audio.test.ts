// Run: npm test
import { test } from 'vitest';
import assert from 'node:assert/strict';

process.env.VITE_MOCK = '0';

// Stand in for the WebView document so the visibilitychange handler registers.
const listeners: Record<string, Array<() => void>> = {};
(globalThis as any).document = {
  addEventListener: (name: string, fn: () => void) => ((listeners[name] ??= []).push(fn)),
};
const fireVisibilityChange = () => listeners['visibilitychange']?.forEach((f) => f());

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
  await new Promise((r) => setTimeout(r, 0)); // the audioControl(false) is dispatched, not awaited
  assert.deepEqual(hw.calls.at(-1), [false, undefined], 'mic must close itself at the cap');
  assert.equal(isCapturing(), true, 'the press is still open until the user stops it');
  // Regression (found in the simulator): the stop press after a cap must not reopen the mic.
  await startCapture(() => {});
  assert.equal(hw.calls.filter(([open]) => open).length, 1);
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

test('WebView suspension: the mic closes and the next press re-arms', async () => {
  const hw = fakeBridge();
  await startCapture(() => {});
  hw.push();
  assert.equal(listeners['visibilitychange']?.length, 1, 'handler must be registered at import');

  fireVisibilityChange(); // phone locked / app backgrounded
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(isCapturing(), false, 'mic must not stay open in the background');
  assert.deepEqual(hw.calls.at(-1), [false, undefined]);
  assert.equal(hw.subscribed, 0);
  assert.equal((await stopCapture()).data_b64, '', 'the buffer is dropped, not sent later');

  fireVisibilityChange(); // relaunched
  await new Promise((r) => setTimeout(r, 0));
  await startCapture(() => {}); // next press
  assert.equal(isCapturing(), true);
  assert.deepEqual(hw.calls.at(-1), [true, 'glasses']);
  hw.push();
  assert.equal(Buffer.from((await stopCapture()).data_b64, 'base64').length, 3200);
});

test('host payload variants: number[] and base64 audioPcm are both captured', async () => {
  setBridge(null);
  let cb: ((e: any) => void) | null = null;
  setBridge({ audioControl: async () => true, onEvenHubEvent: (fn: any) => ((cb = fn), () => (cb = null)) });
  await startCapture(() => {});
  cb!({ audioEvent: { audioPcm: [0, 64, 0, 64], speakerRole: 'self' } });
  cb!({ audioEvent: { audioPcm: Buffer.from([0, 64, 0, 64]).toString('base64'), speakerRole: 'other' } });
  assert.equal(Buffer.from((await stopCapture()).data_b64, 'base64').length, 8);
});

test('host FOREGROUND_EXIT sysEvent closes the mic and drops the buffer', async () => {
  let cb: ((e: any) => void) | null = null;
  const calls: boolean[] = [];
  setBridge({
    audioControl: async (open: boolean) => (calls.push(open), true),
    onEvenHubEvent: (fn: any) => ((cb = fn), () => (cb = null)),
  });
  await startCapture(() => {});
  cb!({ audioEvent: { audioPcm: [0, 64] } });
  cb!({ sysEvent: { eventType: 5 } });
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(isCapturing(), false);
  assert.deepEqual(calls, [true, false]);
  assert.equal((await stopCapture()).data_b64, '');
});

// --- v2: endpointing -------------------------------------------------------------
const tick = () => new Promise((r) => setTimeout(r, 0));
const NOISE = 300; // ~0.009 rms
const SPEECH = 8000; // ~0.24 rms

test('v2 speech_end: 800 ms of silence closes the mic, fires once, and trims leading silence to 200 ms', async () => {
  const hw = fakeBridge();
  const ends: string[] = [];
  await startCapture(() => {}, (r) => ends.push(r));
  for (let i = 0; i < 5; i++) hw.push(NOISE); // 500 ms before speech
  for (let i = 0; i < 10; i++) hw.push(SPEECH); // 1 s of speech
  for (let i = 0; i < 8; i++) hw.push(NOISE); // 800 ms silence
  await tick();
  assert.deepEqual(ends, ['speech_end']);
  assert.deepEqual(hw.calls.at(-1), [false, undefined], 'mic closed at the endpoint, before stopCapture');
  hw.push(NOISE); // late chunk after the endpoint is ignored
  assert.deepEqual(ends, ['speech_end'], 'one endpoint per press');
  const out = await stopCapture();
  // 23 chunks captured; speech started at 500 ms; keep 200 ms of pre-roll -> drop 300 ms.
  assert.equal(Buffer.from(out.data_b64, 'base64').length, 23 * 3200 - 300 * 32);
  assert.equal(isCapturing(), false);
});

test('v2 no_speech: nothing said in 3 s -> mic closed, stopCapture returns data_b64 "" and nothing is sent', async () => {
  const hw = fakeBridge();
  let fetches = 0;
  const realFetch = globalThis.fetch;
  (globalThis as any).fetch = async () => {
    fetches++;
    throw new Error('no network expected');
  };
  // Part 1's contract (README-PART-1 §6): on endpoint, stopCapture; '' means do not ask.
  const { ask } = await import('../src/api/client.ts');
  let asked = false;
  const done = new Promise<void>((resolve) => {
    void startCapture(() => {}, async () => {
      const { data_b64 } = await stopCapture();
      if (data_b64) {
        asked = true;
        await ask({ session_id: 's', audio: { format: 'pcm_s16le', sample_rate: 16000, channels: 1, data_b64 } });
      }
      resolve();
    });
  });
  await tick();
  for (let i = 0; i < 40; i++) hw.push(NOISE); // a stray double nod in a quiet room
  await done;
  assert.equal(asked, false);
  assert.equal(fetches, 0, 'a false trigger costs zero network');
  assert.deepEqual(hw.calls.at(-1), [false, undefined]);
  globalThis.fetch = realFetch;
});

test('v2 cap: 8 s of continuous speech fires cap', async () => {
  const hw = fakeBridge();
  const ends: string[] = [];
  await startCapture(() => {}, (r) => ends.push(r));
  for (let i = 0; i < 3; i++) hw.push(NOISE);
  for (let i = 0; i < 100; i++) hw.push(SPEECH);
  await tick();
  assert.deepEqual(ends, ['cap']);
  const out = await stopCapture();
  assert.ok(Buffer.from(out.data_b64, 'base64').length <= MAX_AUDIO_BYTES);
});

test('v2 manual send (tap / second double nod) before the VAD saw speech sends everything', async () => {
  // A loud shop can defeat the energy VAD; the explicit send must still work.
  const hw = fakeBridge();
  await startCapture(() => {}, () => assert.fail('no endpoint expected'));
  for (let i = 0; i < 12; i++) hw.push(4000); // steady loud noise: floor rises, nothing reads as speech
  const out = await stopCapture();
  assert.equal(Buffer.from(out.data_b64, 'base64').length, 12 * 3200);
});

test('v2 cancel (shake) after an endpoint: buffer dropped, next press gets a fresh endpointer', async () => {
  const hw = fakeBridge();
  const ends: string[] = [];
  await startCapture(() => {}, (r) => ends.push(r));
  for (let i = 0; i < 31; i++) hw.push(NOISE);
  await cancelCapture();
  assert.deepEqual(ends, ['no_speech']);
  await startCapture(() => {}, (r) => ends.push(r));
  for (let i = 0; i < 3; i++) hw.push(NOISE);
  for (let i = 0; i < 5; i++) hw.push(SPEECH);
  for (let i = 0; i < 8; i++) hw.push(NOISE);
  await tick();
  assert.deepEqual(ends, ['no_speech', 'speech_end']);
  const out = await stopCapture();
  assert.ok(out.data_b64.length > 0, 'the no_speech of the previous press does not leak into this one');
});
