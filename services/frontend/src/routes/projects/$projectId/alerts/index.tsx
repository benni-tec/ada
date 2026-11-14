import { createFileRoute } from '@tanstack/react-router'

import { ProjectAlerts } from '@/components/alerts/alert-feed'
import { PageHeader } from '@/components/page-header'

export const Route = createFileRoute('/projects/$projectId/alerts/')({
  component: AlertsPage,
})

/** The project's alerts: its dashboards' alerts and rules, dashboard by dashboard. */
function AlertsPage() {
  const { projectId } = Route.useParams()
  return (
    <div className="flex flex-col gap-8 p-4 md:p-6">
      <PageHeader type="alerts" title="Alerts" />
      <ProjectAlerts projectId={projectId} />
    </div>
  )
}
