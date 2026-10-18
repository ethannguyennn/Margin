import { defineConfig } from 'vitest/config';

export default defineConfig({
  base: '/portal/',
  server: {
    fs: { allow: ['..'] },
    proxy: { '/v1': 'http://127.0.0.1:8080' },
  },
  test: { environment: 'jsdom', include: ['tests/**/*.test.ts'], restoreMocks: true },
});
