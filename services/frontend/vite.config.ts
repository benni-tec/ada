/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    // Must come before the React plugin. Not split under Vitest: each test file then loads
    // the routes while it is imported, instead of lazily inside its first test (where it
    // counted against that test's timeouts, and was transformed once more per route).
    tanstackRouter({ target: 'react', autoCodeSplitting: !process.env.VITEST }),
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // Same port as the frontend container, so the gateway config fits dev and production.
    port: 5173,
    strictPort: true,
    // In development there is no gateway, so Vite forwards API calls itself.
    proxy: {
      '/api': process.env.API_URL ?? 'http://localhost:8000',
      '/mcp': process.env.API_URL ?? 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    // A whole-route test takes up to a second on a quiet machine; leave room for a busy one.
    testTimeout: 15_000,
  },
})
