// Run: npm test
// The endpointer over synthetic RMS sequences, in the host's 100 ms chunks.
import { test } from 'vitest';
import assert from 'node:assert/strict';
import { endpoint, DEFAULT_VAD, Endpointer } from '../src/audio/vad.ts';

const NOISE = 0.01;
const SPEECH = 0.12;
/** [rms, ms] runs -> 100 ms frames. */
const frames = (...runs: Array<[number, number]>) =>
  runs.flatMap(([rms, ms]) => Array.from({ length: ms / 100 }, () => ({ rms, ms: 100 })));

test('speech then 800 ms of silence -> speech_end at exactly 800 ms after the last loud chunk', () => {
  const r = endpoint(frames([NOISE, 500], [SPEECH, 1500], [NOISE, 2000]));
  assert.equal(r.reason, 'speech_end');
  assert.equal(r.atMs, 500 + 1500 + 800);
  assert.equal(r.speechStartMs, 500);
});

test('nobody speaks -> no_speech at 3 s (the false-trigger safety valve)', () => {
  const r = endpoint(frames([NOISE, 5000]));
  assert.deepEqual(r, { reason: 'no_speech', atMs: 3000, speechStartMs: null });
});

test('a pause shorter than 800 ms does not end the utterance', () => {
  const r = endpoint(frames([NOISE, 400], [SPEECH, 800], [NOISE, 700], [SPEECH, 600], [NOISE, 1000]));
  assert.equal(r.reason, 'speech_end');
  assert.equal(r.atMs, 400 + 800 + 700 + 600 + 800);
});

test('a single loud click (< 150 ms) is not speech', () => {
  const r = endpoint(frames([NOISE, 1000], [SPEECH, 100], [NOISE, 3000]));
  assert.equal(r.reason, 'no_speech');
});

test('speech starting late but before 3 s still counts', () => {
  const r = endpoint(frames([NOISE, 2700], [SPEECH, 1000], [NOISE, 1000]));
  assert.equal(r.reason, 'speech_end');
  assert.equal(r.speechStartMs, 2700);
});

test('the floor is relative: a loud shop (0.05) with louder speech (0.2) still endpoints', () => {
  const r = endpoint(frames([0.05, 500], [0.2, 1200], [0.05, 1000]));
  assert.equal(r.reason, 'speech_end');
});

test('talking from the first chunk: maxFloor keeps speech reachable', () => {
  const r = endpoint(frames([0.2, 1500], [NOISE, 1000]));
  assert.equal(r.reason, 'speech_end', 'floor capped at maxFloor (0.05) so 0.2 > 3x floor');
});

test('a dead-silent mic (rms 0) uses minFloor, so faint hiss is not speech', () => {
  const r = endpoint(frames([0, 300], [0.005, 3000]));
  assert.equal(r.reason, 'no_speech');
});

test('the floor tracks down when the room gets quieter after the mic opens', () => {
  const r = endpoint(frames([0.04, 300], [0.008, 1500], [0.06, 600], [0.008, 1000]));
  assert.equal(r.reason, 'speech_end', '0.06 is speech once the floor has fallen from 0.04');
});

test('the endpointer reports once, then stays silent', () => {
  const e = new Endpointer(DEFAULT_VAD);
  const out = frames([NOISE, 4000]).map((f) => e.push(f.rms, f.ms)).filter(Boolean);
  assert.deepEqual(out, ['no_speech']);
});
