// Dark and light are the same design with ink and paper swapped. The choice lives
// on <html data-theme> so the stylesheet can read it, and is remembered locally.
// index.html applies it once before first paint; this keeps it in sync after that.

export type Theme = 'dark' | 'light';

const KEY = 'margin.theme';
const PAGE_COLOR: Record<Theme, string> = { dark: '#0d0d0d', light: '#ffffff' };

export function readStoredTheme(): Theme | null {
  try {
    const stored = localStorage.getItem(KEY);
    return stored === 'light' || stored === 'dark' ? stored : null;
  } catch {
    return null; // storage can be blocked; fall back to the system setting
  }
}

export function systemTheme(): Theme {
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

export function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', PAGE_COLOR[theme]);
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // the attribute above already carries the choice for this visit
  }
}
