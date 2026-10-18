import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Same shape as the lens app's config. The extra allowed host for a remote preview
// arrives through __VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS, which Vite appends itself.
export default defineConfig({
  plugins: [react()],
  server: { host: true, port: 5175, strictPort: true },
  build: { target: 'esnext' },
})
