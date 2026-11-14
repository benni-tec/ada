// Builds every widget under src/widgets/<name> into one self-contained file, dist/<name>.html.
// Each widget is its own Vite build, because a single-file bundle has exactly one entry.
import { readdirSync, renameSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { build } from 'vite'

const here = (path) => fileURLToPath(new URL(path, import.meta.url))

const widgets = readdirSync(here('./src/widgets'), { withFileTypes: true })
  .filter((entry) => entry.isDirectory())
  .map((entry) => entry.name)

rmSync(here('./dist'), { recursive: true, force: true })

for (const widget of widgets) {
  process.env.WIDGET = widget
  await build({ configFile: here('./vite.config.ts'), logLevel: 'warn' })
  renameSync(here('./dist/index.html'), here(`./dist/${widget}.html`))
  console.log(`dist/${widget}.html`)
}
