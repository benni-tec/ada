/// <reference types="vitest/config" />
import { existsSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import { build, defineConfig, type Plugin } from 'vite'
import { viteSingleFile } from 'vite-plugin-singlefile'

const widgetsDir = fileURLToPath(new URL('./src/widgets', import.meta.url))
const srcDir = fileURLToPath(new URL('./src', import.meta.url))

/**
 * `import code from './entry.ts?script'`: the entry and everything it imports bundled into
 * one classic script, as a string. The custom widget writes these into the document of
 * the sandboxed frame that runs its code, which may load nothing (frame.ts).
 *
 * The string is safe inside <script>: "</script" and "<!--" are written as "\x3C/script"
 * and "\x3C!--", as vite-plugin-singlefile does. Tests get an empty script; they run the
 * frame's code directly.
 */
function inlineScripts(): Plugin {
  return {
    name: 'ada-inline-scripts',
    async load(id) {
      const [file, query] = id.split('?')
      if (query !== 'script') return null
      if (process.env.VITEST) return 'export default ""'
      const output = await build({
        configFile: false,
        logLevel: 'warn',
        resolve: { alias: { '@': srcDir } },
        define: { 'process.env.NODE_ENV': '"production"' },
        build: {
          write: false,
          lib: { entry: file, formats: ['iife'], name: 'adaScript' },
          minify: true,
        },
      })
      const [result] = Array.isArray(output) ? output : [output]
      if (!('output' in result)) throw new Error(`${file} did not build`)
      const code = result.output[0].code.replace(/<(\/script|!--)/gi, '\\x3C$1')
      return `export default ${JSON.stringify(code)}`
    },
  }
}

/**
 * Development serves every widget at once, at the same address as the built file:
 * /<type>.html is answered with src/widgets/<type>/index.html. The frontend's iframes then
 * point at the dev server exactly as they point at the built bundles.
 */
function everyWidget(): Plugin {
  return {
    name: 'ada-every-widget',
    configureServer(server) {
      server.middlewares.use((request, _response, next) => {
        const match = request.url?.match(/^\/([\w-]+)\.html(\?.*)?$/)
        if (match && existsSync(`${widgetsDir}/${match[1]}/index.html`)) {
          request.url = `/${match[1]}/index.html${match[2] ?? ''}`
        }
        next()
      })
    },
    // The page keeps the address /<type>.html, so the entry's relative "./main.tsx" would
    // resolve to /main.tsx; anchor it to the widget's folder instead.
    transformIndexHtml: {
      order: 'pre',
      handler(html, { path, server }) {
        if (!server) return html
        const folder = path.replace(/\/index\.html$/, '')
        return html.replace('src="./main.tsx"', `src="${folder}/main.tsx"`)
      },
    },
  }
}

// The build makes one file per widget: build.mjs sets WIDGET for each folder under
// src/widgets and runs one build each, because a single-file bundle has one entry.
const widget = process.env.WIDGET

export default defineConfig(({ command }) => ({
  root: command === 'build' && widget ? `${widgetsDir}/${widget}` : widgetsDir,
  // Scripts and styles are inlined: a widget is one HTML file, served as a ui:// resource
  // and rendered in a sandboxed iframe that may load nothing else.
  plugins: [react(), viteSingleFile(), everyWidget(), inlineScripts()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5174,
    strictPort: true,
    // Same origin for the widget and its data, as behind the gateway: iframes loaded from
    // this server fetch /api here and Vite forwards it to the backend.
    proxy: {
      '/api': process.env.API_URL ?? 'http://localhost:8000',
    },
  },
  build: {
    outDir: fileURLToPath(new URL('./dist', import.meta.url)),
    // build.mjs clears dist once; every widget adds its file.
    emptyOutDir: false,
  },
  test: {
    root: fileURLToPath(new URL('.', import.meta.url)),
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
  },
}))
