import { StrictMode, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'

/** Every widget's entry point: renders it into the #root of its HTML file. */
export function mount(widget: ReactNode) {
  createRoot(document.getElementById('root')!).render(<StrictMode>{widget}</StrictMode>)
}
