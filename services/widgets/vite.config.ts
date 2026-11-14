import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { viteSingleFile } from 'vite-plugin-singlefile'

// One widget per run: build.mjs sets WIDGET for each folder under src/widgets.
// `vite` on its own serves the widget named by WIDGET (default: value) for development.
const widget = process.env.WIDGET ?? 'value'

export default defineConfig({
  root: fileURLToPath(new URL(`./src/widgets/${widget}`, import.meta.url)),
  // Scripts and styles are inlined: a widget is one HTML file, served as a ui:// resource
  // and rendered in a sandboxed iframe that may load nothing else.
  plugins: [react(), viteSingleFile()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5174,
    strictPort: true,
  },
  build: {
    outDir: fileURLToPath(new URL('./dist', import.meta.url)),
    // build.mjs clears dist once; every widget adds its file.
    emptyOutDir: false,
  },
})
