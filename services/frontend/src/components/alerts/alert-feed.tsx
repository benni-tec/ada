import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useId, useState } from 'react'

import { LiveTime } from '@/components/live-time'
import { ErrorNotice, Loading } from '@/components/notices'
import {
  alertFeedQuery,
  projectAlertRulesQuery,
  type AlertState,
  type AlertView,
  type DashboardRules,
  type Id,
} from '@/lib/api'

import { enableBrowserAlerts } from '@/lib/browser-alerts'

import { DashboardRuleList } from './alert-rules'
import { severityPillClasses, worstActive } from './labels'

const filters: { state: AlertState | null; label: string }[] = [
  { state: null, label: 'All' },
  { state: 'firing', label: 'Active' },
  { state: 'resolved', label: 'Ended' },
]

/**
 * The project's alerts, which are its dashboards' alerts: one card per dashboard with a
 * table of its rules, each opening to the alerts it raised. Dashboards with active alerts
 * come first.
 */
export function ProjectAlerts({ projectId }: { projectId: Id }) {
  const [permission, setPermission] = useState<string>()
  const [state, setState] = useState<AlertState | null>(null)
  const feed = useQuery(alertFeedQuery(projectId, state))
  const rules = useQuery(projectAlertRulesQuery(projectId))

  if (feed.isPending || rules.isPending) return <Loading what="alerts" />
  if (feed.error) return <ErrorNotice error={feed.error} prefix="The alerts cannot be loaded:" />
  if (rules.error) return <ErrorNotice error={rules.error} prefix="The alert rules cannot be loaded:" />
  if (rules.data.length === 0) return <p className="text-sm text-muted-foreground">No dashboards yet. Alert rules belong to a dashboard.</p>

  const byRule = new Map<Id, AlertView[]>()
  for (const view of feed.data) byRule.set(view.rule.id, [...(byRule.get(view.rule.id) ?? []), view])
  const active = (group: DashboardRules) =>
    group.rules.reduce((sum, rule) => sum + (byRule.get(rule.id) ?? []).filter((view) => view.alert.state === 'firing').length, 0)
  // Stable: dashboards keep their order within "something is active" and "nothing is".
  const groups = [...rules.data].sort((a, b) => Number(active(b) > 0) - Number(active(a) > 0))
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-2">
        <button type="button" className="rounded-md border px-3 py-1 text-sm" onClick={() => { void enableBrowserAlerts().then(setPermission).catch(() => setPermission('unsupported')) }}>Enable browser alerts</button>
        {permission && <span role="status" className="text-xs">{permission === 'granted' ? 'Browser alerts enabled' : 'In-app alerts enabled; system notifications unavailable'}</span>}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div role="group" aria-label="Show alerts" className="flex gap-1">
          {filters.map((filter) => (
            <button
              key={filter.label}
              type="button"
              aria-pressed={state === filter.state}
              onClick={() => setState(filter.state)}
              className="rounded-md border px-3 py-1 text-sm aria-pressed:bg-primary aria-pressed:text-primary-foreground"
            >
              {filter.label}
            </button>
          ))}
        </div>
        {/* Refetched on every alert event: when this page last heard from the server. */}
        <p className="text-xs text-muted-foreground">
          Updated <LiveTime value={Math.max(feed.dataUpdatedAt, rules.dataUpdatedAt)} />
        </p>
      </div>
      {groups.map((group) => (
        <DashboardAlerts key={group.dashboard.id} projectId={projectId} group={group} alerts={byRule} active={active(group)} />
      ))}
    </div>
  )
}

function DashboardAlerts({
  projectId,
  group,
  alerts,
  active,
}: {
  projectId: Id
  group: DashboardRules
  alerts: ReadonlyMap<Id, AlertView[]>
  active: number
}) {
  const headingId = useId()
  const { dashboard } = group
  // The count's colour is that of the most severe active alert: red only for critical.
  const worst = worstActive(group.rules.flatMap((rule) => alerts.get(rule.id) ?? []))
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3 rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id={headingId} className="text-lg font-semibold">
          <Link to="/projects/$projectId/dashboards/$dashboardId" params={{ projectId, dashboardId: dashboard.id }} className="hover:underline">
            {dashboard.name}
          </Link>
        </h2>
        {active > 0 && worst && (
          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${severityPillClasses[worst]}`}>
            {active} active
          </span>
        )}
      </div>
      <DashboardRuleList projectId={projectId} group={group} alerts={alerts} />
    </section>
  )
}
