import { useStore } from '../store';
import { relayOrigin } from '../relay';

/** Live relay state, from the same /v1/health the lens app polls. Details sit in the tooltip and on the Lens tab. */
export function RelayStatus() {
  const { health, healthChecked } = useStore();
  const state = !healthChecked ? 'checking' : health?.ok ? 'ok' : 'down';
  const label = state === 'checking' ? 'Checking' : state === 'ok' ? (health?.mock ? 'Demo data' : 'Connected') : 'Offline';
  return (
    <span className={`status status-${state}`} title={relayOrigin || 'Server address not configured'}>
      <span className="status-dot" aria-hidden="true" />
      {label}
    </span>
  );
}
