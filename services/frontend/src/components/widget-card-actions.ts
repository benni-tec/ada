import { createContext, type ReactNode } from 'react'

import type { Widget } from '@/lib/api'

/**
 * Actions for the widget cards below it, e.g. "Pin to dashboard" in a session. A context,
 * not only a prop, so a page can add them to cards that a component in between renders.
 */
export const WidgetCardActions = createContext<((widget: Widget) => ReactNode) | null>(null)
