import { Link } from '@tanstack/react-router'
import { Maximize2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import type { Widget } from '@/lib/api'
import type { CardRun } from '@/lib/view-run'

import { Hint } from './icon-action'

declare module '@tanstack/react-router' {
  interface HistoryState {
    /** The run of the card a widget was opened from: the modal shows the same numbers. Kept
     * in the history entry, so going back and forth keeps it; a link from elsewhere has
     * none, and the modal then starts a run of its own, as the widget page does. */
    openRun?: CardRun
  }
}

/**
 * Opens a widget full size over the current page (`?open=<id>`, WidgetModal), at the run
 * of the card it is on. The page stays as it is beneath, scroll position included, so
 * closing the modal (Escape, ×, or the browser's back) returns to exactly where one was.
 * A real link: opened in a new tab, the address shows the widget over the same page.
 */
export function OpenWidgetLink({ widget, run }: { widget: Pick<Widget, 'id' | 'title'>; run: CardRun }) {
  return (
    <Hint label="Open full size">
      <Button asChild variant="ghost" size="icon-sm">
        <Link
          to="."
          search={(previous: Record<string, unknown>) => ({ ...previous, open: widget.id })}
          state={(previous) => ({ ...previous, openRun: run })}
          resetScroll={false}
          aria-label="Open full size"
        >
          <Maximize2 />
        </Link>
      </Button>
    </Hint>
  )
}
