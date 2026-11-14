// `import code from './entry.ts?script'`: the entry bundled into one classic script, as a
// string (the inlineScripts plugin in vite.config.ts).
declare module '*?script' {
  const code: string
  export default code
}
