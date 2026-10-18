import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // Relative asset URLs: the .ehpk is served as files from the Even app, not from a
  // web server root, so /assets/... would not resolve.
  base: './',
  // The simulator smoke keeps its WebView profile in test-artifacts/; watching it reloads the app forever.
  server: { host: true, port: 5173, watch: { ignored: ['**/test-artifacts/**'] } },
  // es2020, not esnext: the Even app's WebView (WKWebView / Android System WebView) can lag
  // desktop browsers, and the bundle must parse on the oldest phone the app supports.
  build: { target: 'es2020' },
})
