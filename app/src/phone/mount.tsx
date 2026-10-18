// The phone screen: the companion UI the Even app shows in its WebView while the
// glasses draw the lens through the SDK bridge (main.ts). Hash routes, because a
// packaged .ehpk is served as files with no server to rewrite /lens or /sops.
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { HashRouter } from 'react-router-dom';
import App from './App';
import { StoreProvider } from './store';
import { initTheme } from './theme';
import './styles.css';

export function mountPhone(root: HTMLElement | null): void {
  if (!root) throw new Error('#root missing from index.html');
  initTheme();
  createRoot(root).render(
    <StrictMode>
      <HashRouter>
        <StoreProvider>
          <App />
        </StoreProvider>
      </HashRouter>
    </StrictMode>,
  );
}
