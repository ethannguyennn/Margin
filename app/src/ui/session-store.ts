/** Debounces navigation writes. Await save() on exit/background to flush the
 * latest session; audio and ordinary answers never enter this string. */
export class SessionStore {
  private pending: string | null = null;
  private written: string;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private waiters: Array<{ resolve(): void; reject(error: unknown): void }> = [];
  private writing: Promise<void> | null = null;
  constructor(private readonly write: (value: string) => Promise<boolean>, initial = '', private readonly delay = 150) {
    this.written = initial;
  }
  save(value: string): Promise<void> {
    if (value === this.written && this.pending === null && !this.writing) return Promise.resolve();
    this.pending = value;
    clearTimeout(this.timer);
    const result = new Promise<void>((resolve, reject) => this.waiters.push({ resolve, reject }));
    this.timer = setTimeout(() => { void this.flush().catch(() => {}); }, this.delay);
    return result;
  }
  async flush(): Promise<void> {
    clearTimeout(this.timer);
    if (this.writing) {
      // A previous caller owns that rejection. A newer queued value must
      // still get its own write attempt and settle its own waiters.
      try { await this.writing; } catch { /* handled by the owning flush */ }
      if (this.pending !== null) await this.flush();
      return;
    }
    if (this.pending === null) return;
    const value = this.pending; this.pending = null;
    const waiters = this.waiters.splice(0);
    this.writing = (async () => {
      if (value !== this.written && !await this.write(value)) throw new Error('Session storage failed');
      this.written = value;
    })();
    try { await this.writing; waiters.forEach(w => w.resolve()); }
    catch (error) { waiters.forEach(w => w.reject(error)); throw error; }
    finally { this.writing = null; }
  }
}
