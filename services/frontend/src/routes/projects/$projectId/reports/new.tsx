import { createFileRoute } from '@tanstack/react-router'

import { GenerateReportForm } from '@/components/reports/generate-report-form'
import { NewReportCrumb } from '@/components/breadcrumbs'

type Search = {
  /** The dashboard to preselect, e.g. when coming from a dashboard's page. */
  dashboard?: string
}

export const Route = createFileRoute('/projects/$projectId/reports/new')({
  staticData: { crumb: NewReportCrumb },
  validateSearch: (search: Record<string, unknown>): Search =>
    typeof search.dashboard === 'string' && search.dashboard !== '' ? { dashboard: search.dashboard } : {},
  component: NewReportPage,
})

function NewReportPage() {
  const { projectId } = Route.useParams()
  const { dashboard } = Route.useSearch()
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">Generate a report from a dashboard</h1>
      <GenerateReportForm projectId={projectId} dashboardId={dashboard} />
    </div>
  )
}
