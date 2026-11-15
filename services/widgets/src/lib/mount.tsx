import { StrictMode, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'

import { answerSnapshots, followFit, followTheme, reportHeight } from './host'

/** Every widget's entry point: renders it into the #root of its HTML file, and when the
 * page sizes the frame to its content, tells the page the height of whatever it shows
 * (loading, an error or the widget); a picture of it when the page asks (a report's PDF). */
export function mount(widget: ReactNode) {
  followTheme()
  followFit()
  const root = document.getElementById('root')!
  reportHeight(root)
  answerSnapshots(root)
  createRoot(root).render(<StrictMode>{widget}</StrictMode>)
}
