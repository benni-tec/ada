import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, RefreshCw } from 'lucide-react'
import { useId, useState } from 'react'

import { IconButton } from '@/components/icon-action'
import { Button } from '@/components/ui/button'

import { ErrorNotice } from '@/components/notices'
import { Time } from '@/components/provenance'
import {
  alertKeys,
  checkAlertRule,
  type AlertRule,
  type CheckResult,
  type DashboardRules,
  type Id,
} from '@/lib/api'

import { asFormula, describe } from './formula'
import { intervalText } from './labels'
import { RuleEditor } from './rule-editor'
import { SeverityBadge } from './severity'

const listClass =
  'divide-y divide-neutral-200 rounded-lg border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800'

/** A dashboard's alert rules, where they are added and edited. */
export function DashboardRuleList({ projectId, group }: { projectId: Id; group: DashboardRules }) {
  const [adding, setAdding] = useState(false)
  const headingId = useId()
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h3 id={headingId} className="text-sm font-medium text-muted-foreground">
          Rules
        </h3>
        {!adding && (
          <Button type="button" variant="outline" size="sm" onClick={() => setAdding(true)}>
            <Plus data-icon="inline-start" aria-hidden="true" />
            New rule
          </Button>
        )}
      </div>
      {adding && <RuleEditor projectId={projectId} dashboardId={group.dashboard.id} onDone={() => setAdding(false)} />}
      {group.rules.length === 0 ? (
        !adding && <p className="text-sm text-neutral-500">No rules on this dashboard.</p>
      ) : (
        <ul className={listClass} aria-label={`Rules of ${group.dashboard.name}`}>
          {group.rules.map((rule) => (
            <RuleItem key={rule.id} projectId={projectId} rule={rule} />
          ))}
        </ul>
      )}
    </section>
  )
}

function checkSummary(result: CheckResult): string {
  const fired = result.changed.filter((alert) => alert.state === 'firing').length
  const resolved = result.changed.length - fired
  const now = result.firing.length
  return `Checked: ${fired} new, ${resolved} resolved, ${now} firing now.`
}

function RuleItem({ projectId, rule }: { projectId: Id; rule: AlertRule }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const check = useMutation({
    mutationFn: () => checkAlertRule(rule.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: alertKeys.all() })
      void queryClient.invalidateQueries({ queryKey: alertKeys.rules() })
    },
  })

  if (editing) {
    return (
      <li className="px-4 py-3">
        <RuleEditor projectId={projectId} dashboardId={rule.dashboard_id} rule={rule} onDone={() => setEditing(false)} />
      </li>
    )
  }

  return (
    <li className="flex flex-col gap-2 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={rule.severity} />
        <span className="font-medium">{rule.name}</span>
        {!rule.enabled && (
          <span className="rounded-full bg-neutral-100 px-2 py-0.5 text-xs text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300">
            Disabled
          </span>
        )}
        <div className="ml-auto flex gap-1">
          <IconButton label="Check now" disabled={check.isPending} onClick={() => check.mutate()}>
            <RefreshCw className={check.isPending ? 'animate-spin motion-reduce:animate-none' : undefined} />
          </IconButton>
          <IconButton label="Edit" onClick={() => setEditing(true)}>
            <Pencil />
          </IconButton>
        </div>
      </div>
      <p className="text-sm">
        Alerts when <code className="rounded bg-neutral-100 px-1.5 py-0.5 font-mono dark:bg-neutral-800">{describe(asFormula(rule.formula))}</code>
        {rule.key_columns.length > 0 && <>, per {rule.key_columns.join(' and ')}</>}
      </p>
      <p className="text-xs text-neutral-600 dark:text-neutral-400">
        Checked {intervalText(rule.check_interval_seconds)}
        {rule.last_checked_at ? (
          <>
            {' · last '}
            <Time value={rule.last_checked_at} />
          </>
        ) : (
          ' · not checked yet'
        )}
      </p>
      {check.data && (
        <p role="status" className="text-xs text-neutral-700 dark:text-neutral-300">
          {checkSummary(check.data)}
        </p>
      )}
      {check.error && <ErrorNotice error={check.error} prefix="The check failed:" />}
    </li>
  )
}
