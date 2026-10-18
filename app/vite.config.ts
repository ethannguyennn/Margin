import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // Relative asset URLs: the .ehpk is served as files from the Even app, not from a
  // web server root, so /assets/... would not resolve.
  base: './',
  server: { host: true, port: 5173 },
  build: { target: 'esnext' },
})
