/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base address of the widget bundles; see src/lib/widgets.ts for the defaults. */
  readonly VITE_WIDGETS_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
