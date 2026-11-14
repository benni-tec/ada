import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { GoToSession } from '@/components/dashboards/pin-to-dashboard'
import { ErrorNotice, Loading } from '@/components/notices'
import { PageHeader } from '@/components/page-header'
import { WidgetCard } from '@/components/widget-card'
import { widgetQuery } from '@/lib/api'
import { useProjectRun, type CardRun } from '@/lib/view-run'

type Search = {
  /** Show the widget at this run instead of starting a new one. */
  run?: string
}

/**
 * One widget on its own page: the address MCP tools give for widgets made outside a
 * session, kept for such direct links. In the app a widget opens full size in a modal
 * over the page instead (`?open=`), so closing it returns to where one was.
 */
export const Route = createFileRoute('/projects/$projectId/widgets/$widgetId')({
  validateSearch: (search: Record<string, unknown>): Search =>
    typeof search.run === 'string' && search.run !== '' ? { run: search.run } : {},
  component: WidgetPage,
})

function WidgetPage() {
  const { projectId, widgetId } = Route.useParams()
  const { run } = Route.useSearch()
  const { data: widget, error, isPending } = useQuery(widgetQuery(widgetId))
  // The run named in the address (a report links to its own this way), else one for this
  // view that follows the data, as a session's.
  const own = useProjectRun(projectId, run === undefined)
  const shown: CardRun = run
    ? { id: run, frozen: true, what: 'the run named in this page’s address' }
    : { id: own.data?.id ?? null, frozen: false, what: 'This page’s current run' }

  if (isPending)
    return (
      <div className="p-6">
        <Loading what="the widget" />
      </div>
    )
  if (error)
    return (
      <div className="p-6">
        <ErrorNotice error={error} prefix="The widget cannot be loaded:" />
      </div>
    )

  return (
    <div className="flex flex-col gap-4 p-4 md:p-6">
      <PageHeader type="widget" title={widget.title || 'Untitled widget'} actions={<GoToSession widget={widget} />} />
      {own.error && <ErrorNotice error={own.error} prefix="The data cannot be read:" />}
      <WidgetCard widget={widget} run={shown} tall openable={false} />
    </div>
  )
}
