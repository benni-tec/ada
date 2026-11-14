import { createContext, type ReactNode } from 'react'

import type { Widget } from '@/lib/api'

/**
 * The icon actions at the right of the footer of the widget cards below it, e.g. "Go to
 * the session it came from" on a dashboard; without one, a card offers "Add to dashboard".
 * A context, not only a prop, so a page can set them for cards that a component in between
 * renders.
 */
export const WidgetCardActions = createContext<((widget: Widget) => ReactNode) | null>(null)
