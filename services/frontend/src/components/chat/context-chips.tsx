import { useQuery } from '@tanstack/react-query'
import { ChartColumn, LayoutDashboard, Workflow, X } from 'lucide-react'
import type { ReactNode } from 'react'

import { Hint } from '@/components/icon-action'
import { Badge } from '@/components/ui/badge'
import { dashboardQuery, pipelinesQuery, widgetQuery, type Context, type Id } from '@/lib/api'

import type { Chip } from './chat-draft'

const icons = { pipeline: Workflow, dashboard: LayoutDashboard, widget: ChartColumn }

/** A chip: what a message is about, with an × to take it off a message being written. */
export function ContextChip({
  kind,
  label,
  onRemove,
}: {
  kind: Context['kind']
  label: ReactNode
  onRemove?: () => void
}) {
  const Icon = icons[kind]
  return (
    <Badge variant="secondary" className="h-6 max-w-full gap-1 pr-1 pl-2 text-xs" data-context={kind}>
      <Icon aria-hidden="true" />
      <span className="truncate">{label}</span>
      {onRemove && (
        <Hint label="Remove">
          <button
            type="button"
            onClick={onRemove}
            aria-label={`Remove ${typeof label === 'string' ? label : 'this chip'}`}
            className="ml-0.5 inline-flex size-4 items-center justify-center rounded-full hover:bg-foreground/10 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            <X className="size-3" />
          </button>
        </Hint>
      )}
    </Badge>
  )
}

/** The chips of the message being written, each removable. */
export function DraftChips({ chips, onRemove }: { chips: Chip[]; onRemove: (key: string) => void }) {
  if (chips.length === 0) return null
  return (
    <ul aria-label="Context" className="flex flex-wrap gap-1.5">
      {chips.map((chip) => (
        <li key={chip.key} className="max-w-full">
          <ContextChip kind={chip.context[0]?.kind ?? 'pipeline'} label={chip.label} onRemove={() => onRemove(chip.key)} />
        </li>
      ))}
    </ul>
  )
}

/** The context a recorded message carried, named from the records it points at. */
export function RecordedContext({ context, projectId }: { context: Context[]; projectId: Id }) {
  if (context.length === 0) return null
  return (
    <ul aria-label="Context" className="flex flex-wrap justify-end gap-1.5">
      {context.map((item, index) => (
        <li key={index} className="max-w-full">
          <ContextChip kind={item.kind} label={<ContextName context={item} projectId={projectId} />} />
        </li>
      ))}
    </ul>
  )
}

function ContextName({ context, projectId }: { context: Context; projectId: Id }) {
  switch (context.kind) {
    case 'pipeline':
      return <PipelineName operatorId={context.operator_id} projectId={projectId} />
    case 'dashboard':
      return <DashboardName dashboardId={context.dashboard_id} slot={context.slot} />
    case 'widget':
      return <WidgetName widgetId={context.widget_id} />
  }
}

function PipelineName({ operatorId, projectId }: { operatorId: string; projectId: Id }) {
  const { data } = useQuery(pipelinesQuery(projectId))
  const name = data?.find((pipeline) => pipeline.operator_id === operatorId)?.name
  return <>Pipeline: {name ?? 'one of the project’s'}</>
}

function DashboardName({ dashboardId, slot }: { dashboardId: Id; slot?: string | null }) {
  const { data } = useQuery(dashboardQuery(dashboardId))
  return (
    <>
      Dashboard: {data?.dashboard.name ?? '…'}
      {slot ? `, slot “${slot}”` : ''}
    </>
  )
}

function WidgetName({ widgetId }: { widgetId: Id }) {
  const { data } = useQuery(widgetQuery(widgetId))
  return <>Widget: {data ? data.title || 'Untitled widget' : '…'}</>
}
