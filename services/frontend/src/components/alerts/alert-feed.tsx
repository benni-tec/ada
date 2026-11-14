import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useId, useState } from 'react'

import { ErrorNotice, Loading } from '@/components/notices'
import { Time } from '@/components/provenance'
import {
  alertFeedQuery,
  alertRowsQuery,
  projectAlertRulesQuery,
  type AlertState,
  type AlertView,
  type DashboardRules,
  type Id,
} from '@/lib/api'
import { cell, cellText, isLong } from '@/lib/cells'

import { DashboardRuleList } from './alert-rules'
import { keyText } from './labels'
import { SeverityBadge } from './severity'

const filters: { state: AlertState | null; label: string }[] = [
  { state: null, label: 'All' },
  { state: 'firing', label: 'Firing' },
  { state: 'resolved', label: 'Resolved' },
]

const listClass =
  'divide-y divide-neutral-200 rounded-lg border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800'

/**
 * The project's alerts, which are its dashboards' alerts: one section per dashboard, with
 * its alerts (firing first, newest first within each state) and its rules. Dashboards with
 * something firing come first.
 */
export function ProjectAlerts({ projectId }: { projectId: Id }) {
  const [state, setState] = useState<AlertState | null>(null)
  const feed = useQuery(alertFeedQuery(projectId, state))
  const rules = useQuery(projectAlertRulesQuery(projectId))

  const filter = (
    <div role="group" aria-label="Show alerts" className="flex gap-1">
      {filters.map((filter) => (
        <button
          key={filter.label}
          type="button"
          aria-pressed={state === filter.state}
          onClick={() => setState(filter.state)}
          className="rounded-md border border-neutral-300 px-3 py-1 text-sm aria-pressed:bg-neutral-900 aria-pressed:text-white dark:border-neutral-700 dark:aria-pressed:bg-neutral-100 dark:aria-pressed:text-neutral-900"
        >
          {filter.label}
        </button>
      ))}
    </div>
  )
  if (feed.isPending || rules.isPending) return <Loading what="alerts" />
  if (feed.error) return <ErrorNotice error={feed.error} prefix="The alerts cannot be loaded:" />
  if (rules.error) return <ErrorNotice error={rules.error} prefix="The alert rules cannot be loaded:" />
  if (rules.data.length === 0) return <p className="text-sm text-neutral-500">No dashboards yet. Alert rules belong to a dashboard.</p>

  const byDashboard = new Map<Id, AlertView[]>()
  for (const view of feed.data) byDashboard.set(view.rule.dashboard_id, [...(byDashboard.get(view.rule.dashboard_id) ?? []), view])
  const firing = (id: Id) => (byDashboard.get(id) ?? []).filter((view) => view.alert.state === 'firing').length
  // Stable: dashboards keep their order within "something fires" and "nothing fires".
  const groups = [...rules.data].sort((a, b) => Number(firing(b.dashboard.id) > 0) - Number(firing(a.dashboard.id) > 0))
  return (
    <div className="flex flex-col gap-6">
      {filter}
      {groups.map((group) => (
        <DashboardAlerts
          key={group.dashboard.id}
          projectId={projectId}
          group={group}
          views={byDashboard.get(group.dashboard.id) ?? []}
          firing={firing(group.dashboard.id)}
          state={state}
        />
      ))}
    </div>
  )
}

function DashboardAlerts({
  projectId,
  group,
  views,
  firing,
  state,
}: {
  projectId: Id
  group: DashboardRules
  views: AlertView[]
  firing: number
  state: AlertState | null
}) {
  const headingId = useId()
  const { dashboard } = group
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id={headingId} className="text-lg font-semibold">
          <Link to="/projects/$projectId/dashboards/$dashboardId" params={{ projectId, dashboardId: dashboard.id }} className="hover:underline">
            {dashboard.name}
          </Link>
        </h2>
        {firing > 0 && (
          <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-800 dark:bg-red-950 dark:text-red-200">
            {firing} firing
          </span>
        )}
      </div>
      {views.length === 0 ? (
        <p className="text-sm text-neutral-500">
          {state === 'firing' ? 'Nothing is firing.' : state === 'resolved' ? 'No resolved alerts.' : 'No alerts yet.'}
        </p>
      ) : (
        <ul className={listClass} aria-label={`Alerts on ${dashboard.name}`}>
          {views.map((view) => (
            <FeedItem key={view.alert.id} view={view} />
          ))}
        </ul>
      )}
      <DashboardRuleList projectId={projectId} group={group} />
    </section>
  )
}

function FeedItem({ view }: { view: AlertView }) {
  const { alert, rule } = view
  const [open, setOpen] = useState(false)
  const rowsId = useId()
  const firing = alert.state === 'firing'
  return (
    <li className="flex flex-col gap-2 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={rule.severity} />
        <span className="font-medium">{keyText(alert.key)}</span>
        <span className="text-sm text-neutral-600 dark:text-neutral-400">· {rule.name}</span>
        <span
          className={`ml-auto text-xs font-medium ${
            firing ? 'text-red-700 dark:text-red-400' : 'text-neutral-500'
          }`}
        >
          {firing ? 'Firing' : 'Resolved'}
        </span>
      </div>
      <p className="text-xs text-neutral-600 dark:text-neutral-400">
        {firing ? 'Since ' : 'Fired '}
        <Time value={alert.started_at} />
        {alert.resolved_at && (
          <>
            {', resolved '}
            <Time value={alert.resolved_at} />
          </>
        )}
      </p>
      <div>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={rowsId}
          onClick={() => setOpen(!open)}
          className="text-xs font-medium underline underline-offset-2"
        >
          {open ? 'Hide the data' : firing ? 'Show the data that fires' : 'Show the data it last fired on'}
        </button>
      </div>
      {open && (
        <div id={rowsId}>
          <AlertRows view={view} />
        </div>
      )}
    </li>
  )
}

/**
 * The rows that raised the alert: the rule's condition over the measure, for the alert's
 * key, in the run that last showed it. A run is a consistent cut, so this is exactly what
 * the check saw. Alerts stored before the condition was kept show the measure's rows.
 */
function AlertRows({ view }: { view: AlertView }) {
  const { alert } = view
  const { data, error, isPending } = useQuery(alertRowsQuery(alert.id))
  if (isPending) return <Loading what="the data" />
  if (error) return <ErrorNotice error={error} prefix="The data cannot be loaded:" />
  const names = data.columns.map((column) => column.name)
  const rows = data.rows.filter((row) =>
    Object.entries(alert.key).every(([column, value]) => String(row[names.indexOf(column)]) === String(value)),
  )
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <caption className="pb-1 text-left text-neutral-500">
          {alert.condition_sql ? 'Alerting rows' : 'Rows'} for {keyText(alert.key)} in run{' '}
          <span className="font-mono">{alert.last_run_id.slice(-8)}</span>
          {data.truncated && ' (the first 1000 rows of the run were searched)'}
        </caption>
        <thead>
          <tr>
            {names.map((name) => (
              <th key={name} scope="col" className="border-b border-neutral-200 px-2 py-1 font-medium dark:border-neutral-800">
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {row.map((value, column) => (
                <td key={column} className="px-2 py-1 tabular-nums" title={isLong(value) ? cellText(value) : undefined}>
                  {cell(value)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
