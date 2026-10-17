/** A timed-out native call may still run. Stop this queue on timeout instead
 * of issuing further calls onto an uncertain BLE connection. */
export class BridgeQueue {
  private tail: Promise<unknown> = Promise.resolve();
  private poisoned: Error | null = null;
  constructor(private readonly timeoutMs = 5000) {}
  run<T>(operation: () => Promise<T>): Promise<T> {
    const next = this.tail.then(async () => {
      if (this.poisoned) throw this.poisoned;
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        return await Promise.race([operation(), new Promise<never>((_, reject) => {
          timer = setTimeout(() => { this.poisoned = new Error('Even bridge timed out; reopen the app'); reject(this.poisoned); }, this.timeoutMs);
        })]);
      } finally { clearTimeout(timer); }
    });
    this.tail = next.catch(() => undefined);
    return next;
  }
}
