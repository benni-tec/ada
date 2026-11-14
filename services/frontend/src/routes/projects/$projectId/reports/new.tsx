import { createFileRoute } from '@tanstack/react-router'

import { PageHeader } from '@/components/page-header'
import { GenerateReportForm } from '@/components/reports/generate-report-form'

type Search = {
  /** The dashboard to preselect, e.g. when coming from a dashboard's page. */
  dashboard?: string
}

export const Route = createFileRoute('/projects/$projectId/reports/new')({
  validateSearch: (search: Record<string, unknown>): Search =>
    typeof search.dashboard === 'string' && search.dashboard !== '' ? { dashboard: search.dashboard } : {},
  component: NewReportPage,
})

function NewReportPage() {
  const { projectId } = Route.useParams()
  const { dashboard } = Route.useSearch()
  return (
    <div className="flex flex-col gap-4 p-4 md:p-6">
      <PageHeader type="report" typeLabel="New report" title="Generate a report from a dashboard" />
      <GenerateReportForm projectId={projectId} dashboardId={dashboard} />
    </div>
  )
}
