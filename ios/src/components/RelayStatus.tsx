import { useStore } from '../store';
import { relayOrigin } from '../relay';

/** Live relay state, from the same /v1/health the lens app polls. */
export function RelayStatus() {
  const { health, healthChecked } = useStore();
  const label = !healthChecked ? 'Checking relay' : health?.ok ? `Relay ok · ${health.mock ? 'mock' : 'live'}` : 'Relay unreachable';
  const tone = !healthChecked ? ' dim' : health?.ok ? '' : ' solid';

  return (
    <span className={`chip${tone}`} title={relayOrigin || 'VITE_RELAY_ORIGIN is not set'}>
      {label}
    </span>
  );
}
