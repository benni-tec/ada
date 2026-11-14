import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useId, useState, type FormEvent } from 'react'

import { ErrorNotice, Loading } from '@/components/notices'
import { dashboardsQuery, generateReport, reportKeys, type Id } from '@/lib/api'

const fieldClass =
  'rounded-md border border-neutral-300 bg-white px-3 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900'

/**
 * Freezes a dashboard of the project into a report: its current widgets at a new run of
 * its default time range. Generating again under the same name adds the report's next
 * version, so a monthly report keeps one name and a history.
 */
export function GenerateReportForm({ projectId, dashboardId }: { projectId: Id; dashboardId?: string }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const dashboardFieldId = useId()
  const nameFieldId = useId()
  const hintId = useId()
  const { data: dashboards, error, isPending } = useQuery(dashboardsQuery(projectId))
  const [chosen, setChosen] = useState(dashboardId ?? '')
  const [name, setName] = useState('')

  const generate = useMutation({
    mutationFn: () => generateReport(chosen, name.trim()),
    onSuccess: async (version) => {
      await queryClient.invalidateQueries({ queryKey: reportKeys.reports(projectId) })
      await queryClient.invalidateQueries({ queryKey: reportKeys.report(version.report_id) })
      await navigate({
        to: '/projects/$projectId/reports/$reportId',
        params: { projectId, reportId: version.report_id },
        search: { version: version.version },
      })
    },
  })

  if (isPending) return <Loading what="dashboards" />
  if (error) return <ErrorNotice error={error} prefix="The dashboards cannot be loaded:" />
  if (dashboards.length === 0) {
    return <p className="text-sm text-neutral-500">This project has no dashboards to generate a report from.</p>
  }

  const selected = chosen !== '' && dashboards.some((dashboard) => dashboard.id === chosen) ? chosen : ''
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (selected !== '' && name.trim() !== '') generate.mutate()
  }

  return (
    <form onSubmit={submit} className="flex max-w-xl flex-col gap-4" aria-describedby={hintId}>
      <p id={hintId} className="text-sm text-neutral-600 dark:text-neutral-400">
        The report shows the dashboard’s current widgets at one run of its default time range, and keeps those
        numbers. A report of the same name gets its next version.
      </p>
      <div className="flex flex-col gap-1">
        <label htmlFor={dashboardFieldId} className="text-sm font-medium">
          Dashboard
        </label>
        <select
          id={dashboardFieldId}
          value={selected}
          onChange={(event) => setChosen(event.target.value)}
          required
          className={fieldClass}
        >
          <option value="" disabled>
            Choose a dashboard
          </option>
          {dashboards.map((dashboard) => (
            <option key={dashboard.id} value={dashboard.id}>
              {dashboard.name}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor={nameFieldId} className="text-sm font-medium">
          Report name
        </label>
        <input
          id={nameFieldId}
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="e.g. Screening coverage, monthly"
          required
          className={fieldClass}
        />
      </div>
      <div>
        <button
          type="submit"
          disabled={generate.isPending || selected === '' || name.trim() === ''}
          className="rounded-md bg-neutral-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900"
        >
          {generate.isPending ? 'Generating…' : 'Generate report'}
        </button>
      </div>
      {generate.error && <ErrorNotice error={generate.error} prefix="Not generated:" />}
    </form>
  )
}
