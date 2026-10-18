import type { Theme } from '../theme';

/** The same screen in the other light: no colour changes, only ink and paper. */
export function ThemeToggle({ theme, onToggle }: { theme: Theme; onToggle: () => void }) {
  const next = theme === 'dark' ? 'light' : 'dark';

  return (
    <button type="button" className="btn" onClick={onToggle} aria-label={`Switch to ${next} mode`}>
      {next === 'light' ? 'Light mode' : 'Dark mode'}
    </button>
  );
}
