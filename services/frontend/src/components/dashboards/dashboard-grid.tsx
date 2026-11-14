import type { CSSProperties, ReactNode } from 'react'

import { WidgetCard } from '@/components/widget-card'
import { WidgetCardActions } from '@/components/widget-card-actions'
import { slotLayout, type DashboardSlot, type Id, type Widget } from '@/lib/api'
import type { CardRun } from '@/lib/view-run'

import { GoToSession } from './pin-to-dashboard'

type Widgets = Map<Id, Widget>

/** What a slot holds: the widget on the shared run, or why there is none. */
function SlotContent({ slot, widgets, run }: { slot: DashboardSlot; widgets: Widgets; run: CardRun }) {
  const widget = slot.widget_id ? widgets.get(slot.widget_id) : undefined
  if (widget) return <WidgetCard widget={widget} run={run} />
  return (
    <div className="flex min-h-32 flex-col justify-center gap-1 rounded-lg border border-dashed border-neutral-300 p-4 text-sm text-neutral-500 dark:border-neutral-700">
      {slot.widget_id ? (
        <p>This slot’s widget is not available.</p>
      ) : (
        <p>Empty slot{slot.description ? `: ${slot.description}` : '.'}</p>
      )}
    </div>
  )
}

/** A widget on a dashboard is on one already: its action leads back to where it was made. */
function OnDashboard({ children }: { children: ReactNode }) {
  return <WidgetCardActions value={(widget) => <GoToSession widget={widget} />}>{children}</WidgetCardActions>
}

function SlotName({ slot }: { slot: DashboardSlot }) {
  return <p className="mb-1 truncate text-xs font-medium text-neutral-600 dark:text-neutral-400">{slot.name}</p>
}

/**
 * The slots on the 12-column grid, every widget reading the one run. Below the `md`
 * breakpoint the grid is a single column in reading order, since a 12-column layout does
 * not fit a phone. Rows have no fixed height: a card is as tall as its widget needs.
 */
export function DashboardGrid({
  slots,
  widgets,
  run,
}: {
  slots: readonly DashboardSlot[]
  widgets: Widgets
  /** The dashboard's run: every widget reads it. */
  run: CardRun
}) {
  if (slots.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-neutral-300 p-6 text-center text-sm text-neutral-500 dark:border-neutral-700">
        Nothing is pinned yet. Pin a widget from a session, or let an agent do it over MCP.
      </p>
    )
  }
  return (
    <OnDashboard>
    <ul aria-label="Dashboard widgets" className="grid auto-rows-[minmax(5rem,auto)] grid-cols-1 gap-4 md:grid-cols-12">
      {slots.map((slot) => {
        const { x, y, w, h } = slotLayout(slot)
        const place = { '--col': `${x + 1} / span ${w}`, '--row': `${y + 1} / span ${h}` } as CSSProperties
        return (
          <li key={slot.name} style={place} className="min-w-0 md:[grid-column:var(--col)] md:[grid-row:var(--row)]">
            <SlotName slot={slot} />
            <SlotContent slot={slot} widgets={widgets} run={run} />
          </li>
        )
      })}
    </ul>
    </OnDashboard>
  )
}

/** The same slots in one column, in reading order (top to bottom, left to right): for the
 * panel beside a conversation, which is too narrow for the grid. */
export function CompactGrid({
  slots,
  widgets,
  run,
}: {
  slots: readonly DashboardSlot[]
  widgets: Widgets
  /** The dashboard's run: every widget reads it. */
  run: CardRun
}) {
  if (slots.length === 0) return <p className="text-sm text-neutral-500">Nothing is pinned to this dashboard yet.</p>
  const ordered = [...slots].sort((a, b) => {
    const [p, q] = [slotLayout(a), slotLayout(b)]
    return p.y - q.y || p.x - q.x
  })
  return (
    <OnDashboard>
    <ul aria-label="Dashboard widgets" className="flex flex-col gap-3">
      {ordered.map((slot) => (
        <li key={slot.name} className="min-w-0">
          <SlotName slot={slot} />
          <SlotContent slot={slot} widgets={widgets} run={run} />
        </li>
      ))}
    </ul>
    </OnDashboard>
  )
}
