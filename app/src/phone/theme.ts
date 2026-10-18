// Light / dark for the phone screen. Follows the OS until the user picks one,
// then the pick is kept in localStorage and set as data-theme on <html>.
import { useEffect, useState } from 'react';

export type Theme = 'light' | 'dark';

const KEY = 'specs.phone.theme';
const query = () => window.matchMedia?.('(prefers-color-scheme: dark)');

function stored(): Theme | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw === 'light' || raw === 'dark' ? raw : null;
  } catch {
    return null;
  }
}

function systemTheme(): Theme {
  return query()?.matches ? 'dark' : 'light';
}

function apply(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#000000' : '#ffffff');
}

/** Called once before the first render so the page never flashes the wrong theme. */
export function initTheme(): void {
  apply(stored() ?? systemTheme());
}

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => stored() ?? systemTheme());

  useEffect(() => apply(theme), [theme]);

  useEffect(() => {
    const mq = query();
    if (!mq) return;
    const onChange = () => {
      if (!stored()) setTheme(systemTheme());
    };
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  const toggle = () => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark';
    try {
      localStorage.setItem(KEY, next);
    } catch {
      // Private mode or blocked storage: the pick still holds for this session.
    }
    setTheme(next);
  };

  return [theme, toggle];
}
