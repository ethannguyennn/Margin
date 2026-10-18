import { useCallback, useEffect, useState } from 'react';
import { applyTheme, readStoredTheme, systemTheme, type Theme } from '../theme';

/** One theme for the whole app; the toggle in the header flips it. */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => readStoredTheme() ?? systemTheme());

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((current) => (current === 'dark' ? 'light' : 'dark'));
  }, []);

  return { theme, toggle };
}
