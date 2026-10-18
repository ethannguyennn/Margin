// Pure silence endpointer: per-chunk RMS in, 'speech_end' | 'no_speech' out.
// Energy only - shop noise will beat it sometimes, which is why a second double nod or
// a tap sends immediately and a shake cancels (Part 1 wires those).
export type EndpointReason = 'speech_end' | 'no_speech' | 'cap';

export interface VadParams {
  floorMs: number; // noise floor = median RMS of this much audio after the mic opens
  k: number; // speech when RMS > floor x k
  minFloor: number; // a dead-silent mic must not make every click "speech"
  maxFloor: number; // talking from the first chunk must not make speech unreachable
  minSpeechMs: number; // above threshold this long = speech started
  silenceMs: number; // below threshold this long after speech = speech_end
  noSpeechMs: number; // no speech by then = no_speech (false-trigger safety valve)
}

export const DEFAULT_VAD: VadParams = {
  floorMs: 300,
  k: 3,
  minFloor: 0.003,
  maxFloor: 0.05,
  minSpeechMs: 150,
  silenceMs: 800,
  noSpeechMs: 3000,
};

export class Endpointer {
  private ms = 0;
  private early: number[] = [];
  private floor = 0;
  private above = 0; // ms continuously above threshold
  private below = 0; // ms continuously below threshold, after speech
  private done = false;
  /** ms from mic open to the first chunk of the speech run; null until speech is confirmed. */
  speechStartMs: number | null = null;

  constructor(readonly params: VadParams = DEFAULT_VAD) {}

  /** One chunk: its RMS (0..1) and duration. Returns an endpoint once, then null forever. */
  push(rms: number, chunkMs: number): Exclude<EndpointReason, 'cap'> | null {
    if (this.done) return null;
    const P = this.params;
    const at = this.ms;
    this.ms += chunkMs;
    if (at < P.floorMs) {
      this.early.push(rms);
      const s = [...this.early].sort((a, b) => a - b);
      this.floor = Math.min(P.maxFloor, Math.max(P.minFloor, s[Math.floor(s.length / 2)]));
    } else if (rms < this.floor) {
      this.floor = Math.max(P.minFloor, 0.9 * this.floor + 0.1 * rms); // track a quieter room down
    }
    const loud = rms > this.floor * P.k;
    if (this.speechStartMs === null) {
      this.above = loud ? this.above + chunkMs : 0;
      if (this.above >= P.minSpeechMs) {
        this.speechStartMs = this.ms - this.above;
      } else if (this.ms >= P.noSpeechMs) {
        this.done = true;
        return 'no_speech';
      }
      return null;
    }
    this.below = loud ? 0 : this.below + chunkMs;
    if (this.below >= P.silenceMs) {
      this.done = true;
      return 'speech_end';
    }
    return null;
  }
}

/** Pure, for tests: run a whole RMS sequence. */
export function endpoint(
  frames: { rms: number; ms: number }[],
  params: VadParams = DEFAULT_VAD,
): { reason: Exclude<EndpointReason, 'cap'> | null; atMs: number; speechStartMs: number | null } {
  const e = new Endpointer(params);
  let atMs = 0;
  for (const f of frames) {
    atMs += f.ms;
    const reason = e.push(f.rms, f.ms);
    if (reason) return { reason, atMs, speechStartMs: e.speechStartMs };
  }
  return { reason: null, atMs, speechStartMs: e.speechStartMs };
}
