/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    // Must come before the React plugin.
    tanstackRouter({ target: 'react', autoCodeSplitting: true }),
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
    // Whole routes render in these tests; on a busy machine the defaults time out.
    testTimeout: 60_000,
  },
})
