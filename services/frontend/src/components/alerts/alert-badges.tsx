import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Bell } from 'lucide-react'

import { Hint } from '@/components/icon-action'
import { LiveTime } from '@/components/live-time'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { dashboardAlertsQuery, type Id } from '@/lib/api'
import { cn } from '@/lib/utils'

import { countBySeverity, countsText, keyText, mostSevereFirst, severityPillClasses, worstActive } from './labels'
import { SeverityBadge } from './severity'

/**
 * A dashboard's alerts as a bell at the top of the page: the number of active alerts of
 * its rules, coloured by the most severe of them (red only for critical), opening the
 * list of them with the way to all alerts. Shows nothing while loading or when the
 * dashboard has no rules; a quiet bell when nothing is active.
 */
export function AlertBadges({ projectId, dashboardId }: { projectId: Id; dashboardId: Id }) {
  const { data } = useQuery(dashboardAlertsQuery(dashboardId))
  if (!data) return null
  // The most severe first: a critical alert is never buried under warnings.
  const active = mostSevereFirst(data.filter((view) => view.alert.state === 'firing'))
  const worst = worstActive(data)
  const label =
    active.length === 0
      ? 'No active alerts'
      : `${active.length} active ${active.length === 1 ? 'alert' : 'alerts'}: ${countsText(countBySeverity(data))}`
  return (
    <Popover>
      <Hint label={label}>
        <PopoverTrigger asChild>
          <Button variant="outline" size="sm" aria-label={label} data-severity={worst ?? undefined}>
            <Bell aria-hidden="true" className={worst ? undefined : 'text-muted-foreground'} />
            {worst && (
              <span className={cn('rounded-full px-1.5 text-xs font-medium tabular-nums', severityPillClasses[worst])}>
                {active.length}
              </span>
            )}
          </Button>
        </PopoverTrigger>
      </Hint>
      <PopoverContent align="end" className="w-80 p-0">
        <div className="border-b px-3 py-2 text-sm font-medium">Active alerts</div>
        {active.length === 0 ? (
          <p className="px-3 py-3 text-sm text-muted-foreground">Nothing is active on this dashboard.</p>
        ) : (
          <ul aria-label="Active alerts" className="max-h-72 divide-y overflow-y-auto">
            {active.map(({ alert, rule }) => (
              <li key={alert.id} className="flex flex-col gap-1 px-3 py-2 text-sm">
                <div className="flex items-center gap-2">
                  <SeverityBadge severity={rule.severity} />
                  <span className="min-w-0 truncate font-medium">{keyText(alert.key)}</span>
                </div>
                <div className="text-xs text-muted-foreground">
                  {rule.name} · since <LiveTime value={alert.started_at} />
                </div>
              </li>
            ))}
          </ul>
        )}
        <div className="border-t px-3 py-2">
          <Link to="/projects/$projectId/alerts" params={{ projectId }} className="text-sm font-medium hover:underline">
            Open all alerts
          </Link>
        </div>
      </PopoverContent>
    </Popover>
  )
}
