import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'

import { ErrorNotice, Loading } from '@/components/notices'
import { WidgetCard } from '@/components/widget-card'
import { widgetQuery } from '@/lib/api'

type Search = {
  /** Show the widget at this run instead of starting a new one. */
  run?: string
}

export const Route = createFileRoute('/projects/$projectId/widgets/$widgetId')({
  validateSearch: (search: Record<string, unknown>): Search =>
    typeof search.run === 'string' && search.run !== '' ? { run: search.run } : {},
  component: WidgetPage,
})

function WidgetPage() {
  const { projectId, widgetId } = Route.useParams()
  const { run } = Route.useSearch()
  const { data: widget, error, isPending } = useQuery(widgetQuery(widgetId))

  if (isPending) return <Loading what="the widget" />
  if (error) return <ErrorNotice error={error} prefix="The widget cannot be loaded:" />

  return (
    <div className="flex flex-col gap-4">
      <h1 className="sr-only">{widget.title || 'Widget'}</h1>
      <WidgetCard widget={widget} runId={run} tall linkToWidget={false} />
      {widget.session_id && (
        <p className="text-sm">
          <Link
            to="/projects/$projectId/sessions/$sessionId"
            params={{ projectId, sessionId: widget.session_id }}
            search={{ widget: widget.id }}
            className="text-blue-700 underline-offset-2 hover:underline dark:text-blue-400"
          >
            Show it in its session
          </Link>
        </p>
      )}
    </div>
  )
}
