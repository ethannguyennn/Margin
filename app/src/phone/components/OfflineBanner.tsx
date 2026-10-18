import { useEffect, useRef, useState } from 'react';
import { useStore } from '../store';
import { toast } from '../toast';

/** A bar under the header while /v1/health fails, with a Retry that re-polls at once. */
export function OfflineBanner() {
  const { health, healthChecked, recheckHealth } = useStore();
  const [retrying, setRetrying] = useState(false);
  const offline = healthChecked && !health?.ok;
  const wasOffline = useRef(false);

  useEffect(() => {
    if (wasOffline.current && !offline) toast('Back online');
    wasOffline.current = offline;
  }, [offline]);

  if (!offline) return null;

  const retry = async () => {
    setRetrying(true);
    try {
      await recheckHealth();
    } finally {
      setRetrying(false);
    }
  };

  return (
    <div className="offline-bar" role="alert">
      <span className="offline-text">
        <strong>Offline.</strong> Answers and procedures are unavailable.
      </span>
      <button className="offline-retry" aria-busy={retrying} disabled={retrying} onClick={() => void retry()}>
        {retrying ? 'Retrying…' : 'Retry'}
      </button>
    </div>
  );
}

/** A failed load (procedures, steps) as one plain sentence and a Retry. */
export function LoadError({ message, detail, onRetry }: { message: string; detail?: string; onRetry: () => void }) {
  return (
    <div className="load-error" role="alert">
      <p className="error-line" title={detail}>
        {message}
      </p>
      <button className="ghost" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}
