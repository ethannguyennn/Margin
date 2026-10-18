// Brief confirmations ("Deviation logged") shown above the tab bar. Any component
// calls toast(); the one <Toaster /> in App renders the latest message.
import { useEffect, useState } from 'react';

type Listener = (message: string) => void;
const listeners = new Set<Listener>();

export function toast(message: string): void {
  listeners.forEach((listen) => listen(message));
}

export function Toaster() {
  const [current, setCurrent] = useState<{ message: string; id: number } | null>(null);

  useEffect(() => {
    const listen: Listener = (message) => setCurrent((prev) => ({ message, id: (prev?.id ?? 0) + 1 }));
    listeners.add(listen);
    return () => {
      listeners.delete(listen);
    };
  }, []);

  useEffect(() => {
    if (!current) return;
    const timer = setTimeout(() => setCurrent(null), 2400);
    return () => clearTimeout(timer);
  }, [current]);

  return (
    <div className="toast-region" role="status" aria-live="polite">
      {current && (
        <div key={current.id} className="toast">
          {current.message}
        </div>
      )}
    </div>
  );
}
