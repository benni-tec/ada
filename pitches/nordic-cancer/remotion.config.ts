// The pitch renders ADA's own components (services/frontend) with scripted data: the same
// `@/` alias, Tailwind theme and React as the app.
import path from 'node:path'

import { webpack } from '@remotion/bundler'
import { Config } from '@remotion/cli/config'
import { enableTailwind } from '@remotion/tailwind-v4'

const frontend = path.resolve(process.cwd(), '../../services/frontend')

Config.setVideoImageFormat('jpeg')
Config.overrideWebpackConfig((config) => {
  const withTailwind = enableTailwind(config)
  return {
    ...withTailwind,
    resolve: {
      ...withTailwind.resolve,
      alias: {
        ...(withTailwind.resolve?.alias as Record<string, string> | undefined),
        '@': path.join(frontend, 'src'),
        // One React for Remotion and the app's components.
        react: path.join(frontend, 'node_modules/react'),
        'react-dom': path.join(frontend, 'node_modules/react-dom'),
      },
    },
    plugins: [
      ...(withTailwind.plugins ?? []),
      // A few app modules read Vite's env; nothing here depends on its values.
      new webpack.DefinePlugin({ 'import.meta.env': JSON.stringify({ DEV: false, PROD: true, MODE: 'production' }) }),
    ],
  }
})
