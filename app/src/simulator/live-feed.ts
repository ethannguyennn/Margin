import type { DiagramImage } from '../types';
import type { ScreenText } from '../ui/screens';
export interface DisplayFrame { screen: string; frame: ScreenText; diagram?: DiagramImage }
export interface LiveDisplay extends Partial<DisplayFrame> {
  device_id: string; worker_name?: string; live: boolean; last_seen: number | null; sequence?: number;
}
export type FeedRequest = <T>(path: string, init?: RequestInit) => Promise<T>;

/** Only acknowledged hardware renders enter this coalesced, serialized feed. */
export class DisplayPublisher {
  private latest?: DisplayFrame;
  private stream?: string;
  private sequence = 0;
  private active = true;
  private stopped = false;
  private dirty = false;
  private beats = 0;
  private timer: ReturnType<typeof setTimeout>;
  private abort = new AbortController();
  constructor(private request: FeedRequest, private interval = 500) {
    this.timer = setTimeout(() => void this.tick(), interval);
  }
  acknowledged(frame: DisplayFrame) { this.latest = frame; this.dirty = true; }
  setActive(active: boolean) { this.active = active; this.dirty = true; }
  dispose() { this.stopped = true; clearTimeout(this.timer); this.abort.abort(); }
  private async tick() {
    if (this.stopped) return;
    try {
      if (!this.latest || (!this.dirty && (!this.active || ++this.beats < 6))) return;
      this.beats = 0;
      const options = { signal: this.abort.signal };
      if (!this.stream) {
        const result = await this.request<{ stream_id: string }>('/v1/lens/display/stream', { ...options, method: 'POST' });
        this.stream = result.stream_id; this.sequence = 0;
      }
      const body = { ...this.latest, stream_id: this.stream, sequence: ++this.sequence, connected: this.active };
      this.dirty = false;
      await this.request('/v1/lens/display', { ...options, method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    } catch (error) {
      this.dirty = true;
      const status = (error as { status?: number }).status;
      if (status === 410) this.stream = undefined;
      if (status === 409) this.dispose(); // a newer launch owns the feed
    } finally {
      if (!this.stopped) this.timer = setTimeout(() => void this.tick(), this.interval);
    }
  }
}
