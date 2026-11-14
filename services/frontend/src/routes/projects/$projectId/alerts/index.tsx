import { createFileRoute } from '@tanstack/react-router'

import { AlertFeed } from '@/components/alerts/alert-feed'
import { AlertRules } from '@/components/alerts/alert-rules'

export const Route = createFileRoute('/projects/$projectId/alerts/')({
  component: AlertsPage,
})

/** The project's alerts: the feed of what fires and has fired, and each dashboard's rules. */
function AlertsPage() {
  const { projectId } = Route.useParams()
  return (
    <div className="flex flex-col gap-8">
      <h1 className="text-2xl font-semibold">Alerts</h1>
      <AlertFeed projectId={projectId} />
      <AlertRules projectId={projectId} />
    </div>
  )
}
