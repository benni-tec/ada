import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronRight, Pencil, Plus, RefreshCw } from 'lucide-react'
import { useId, useState } from 'react'

import { IconButton } from '@/components/icon-action'
import { LiveTime } from '@/components/live-time'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

import { ErrorNotice } from '@/components/notices'
import {
  alertKeys,
  checkAlertRule,
  testAlertRule,
  type AlertRule,
  type AlertView,
  type CheckResult,
  type DashboardRules,
  type Id,
} from '@/lib/api'

import { showBrowserAlert } from '@/lib/browser-alerts'

import { Deliveries } from './deliveries'
import { AlertTable } from './alert-table'
import { asFormula, describe } from './formula'
import { intervalText, keyText, severityTextClasses } from './labels'
import { RuleEditor } from './rule-editor'
import { SeverityBadge } from './severity'

/**
 * A dashboard's alert rules as a table, where they are added and edited. A rule with alerts
 * opens to them, a table in its row; one with an active alert starts open.
 */
export function DashboardRuleList({
  projectId,
  group,
  alerts,
}: {
  projectId: Id
  group: DashboardRules
  alerts: ReadonlyMap<Id, AlertView[]>
}) {
  const [adding, setAdding] = useState(false)
  return (
    <div className="flex flex-col gap-2">
      {group.rules.length === 0 ? (
        !adding && <p className="text-sm text-muted-foreground">No rules on this dashboard.</p>
      ) : (
        <Table aria-label={`Rules of ${group.dashboard.name}`}>
          <TableHeader>
            <TableRow>
              <TableHead className="w-0">
                <span className="sr-only">Alerts</span>
              </TableHead>
              <TableHead>Severity</TableHead>
              <TableHead>Rule</TableHead>
              <TableHead>Alerts when</TableHead>
              <TableHead>Checked</TableHead>
              <TableHead>Alerts</TableHead>
              <TableHead>
                <span className="sr-only">Actions</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {group.rules.map((rule) => (
              <RuleRow key={rule.id} projectId={projectId} rule={rule} alerts={alerts.get(rule.id) ?? []} />
            ))}
          </TableBody>
        </Table>
      )}
      {adding ? (
        <RuleEditor projectId={projectId} dashboardId={group.dashboard.id} onDone={() => setAdding(false)} />
      ) : (
        <Button type="button" variant="outline" size="sm" className="self-start" onClick={() => setAdding(true)}>
          <Plus data-icon="inline-start" aria-hidden="true" />
          New rule
        </Button>
      )}
    </div>
  )
}

function checkSummary(result: CheckResult): string {
  const fired = result.changed.filter((alert) => alert.state === 'firing').length
  const resolved = result.changed.length - fired
  const now = result.firing.length
  return `Checked: ${fired} new, ${resolved} ended, ${now} active now.`
}

/** One rule as a table row; editing it opens the editor in a row of its own. */
function RuleRow({ projectId, rule, alerts }: { projectId: Id; rule: AlertRule; alerts: AlertView[] }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const active = alerts.filter((view) => view.alert.state === 'firing').length
  const [open, setOpen] = useState<boolean>()
  const shown = open ?? active > 0
  const alertsId = useId()
  const test = useMutation({
    mutationFn: () => testAlertRule(rule.id),
    onSuccess: (alert) => {
      showBrowserAlert(`[TEST] ${rule.name}`, keyText(alert.key), alert.id, projectId)
      void queryClient.invalidateQueries({ queryKey: alertKeys.all() })
    },
  })
  const check = useMutation({
    mutationFn: () => checkAlertRule(rule.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: alertKeys.all() })
      void queryClient.invalidateQueries({ queryKey: alertKeys.rules() })
    },
  })

  if (editing) {
    return (
      <TableRow className="hover:bg-transparent">
        <TableCell colSpan={7} className="whitespace-normal">
          <RuleEditor projectId={projectId} dashboardId={rule.dashboard_id} rule={rule} onDone={() => setEditing(false)} />
        </TableCell>
      </TableRow>
    )
  }

  return (
    <>
    <TableRow data-state={shown ? 'selected' : undefined}>
      <TableCell>
        {alerts.length > 0 && (
          <IconButton
            label={shown ? 'Hide its alerts' : 'Show its alerts'}
            aria-expanded={shown}
            aria-controls={alertsId}
            onClick={() => setOpen(!shown)}
          >
            <ChevronRight className={shown ? 'rotate-90 transition-transform' : 'transition-transform'} />
          </IconButton>
        )}
      </TableCell>
      <TableCell>
        <SeverityBadge severity={rule.severity} />
      </TableCell>
      <TableCell>
        <span className="font-medium">{rule.name}</span>
        {!rule.enabled && (
          <span className="ml-2 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">Disabled</span>
        )}
      </TableCell>
      <TableCell className="whitespace-normal">
        <code className="rounded bg-muted px-1.5 py-0.5 font-mono">{describe(asFormula(rule.formula))}</code>
        {rule.key_columns.length > 0 && <span className="text-muted-foreground">, per {rule.key_columns.join(' and ')}</span>}
      </TableCell>
      <TableCell className="whitespace-normal text-muted-foreground">
        {intervalText(rule.check_interval_seconds)}
        {rule.last_checked_at ? (
          <>
            {' · last '}
            <LiveTime value={rule.last_checked_at} />
          </>
        ) : (
          ' · not checked yet'
        )}
        {check.data && (
          <p role="status" className="text-xs text-foreground">
            {checkSummary(check.data)}
          </p>
        )}
        {test.error && <ErrorNotice error={test.error} prefix="Test send failed:" />}
        {test.isSuccess && <p role="status">Test alert queued</p>}
        {check.error && <ErrorNotice error={check.error} prefix="The check failed:" />}
      </TableCell>
      <TableCell className={active > 0 ? severityTextClasses[rule.severity] : 'text-muted-foreground'}>
        {active > 0 ? `${active} active` : alerts.length > 0 ? `${alerts.length} ended` : 'None'}
      </TableCell>
      <TableCell className="w-0">
        <div className="flex justify-end gap-1">
          <button type="button" className="whitespace-nowrap text-xs underline" disabled={test.isPending} onClick={() => test.mutate()}>Send test alert</button>
          <IconButton label="Check now" disabled={check.isPending} onClick={() => check.mutate()}>
            <RefreshCw className={check.isPending ? 'animate-spin motion-reduce:animate-none' : undefined} />
          </IconButton>
          <IconButton label="Edit" onClick={() => setEditing(true)}>
            <Pencil />
          </IconButton>
        </div>
      </TableCell>
    </TableRow>
    <TableRow><TableCell colSpan={7}><Deliveries projectId={projectId} ruleId={rule.id} browserAlertId={test.data?.id} /></TableCell></TableRow>
    {shown && alerts.length > 0 && (
      <TableRow className="hover:bg-transparent">
        <TableCell colSpan={7} id={alertsId} className="bg-muted/30 py-2 pl-12 whitespace-normal">
          <AlertTable views={alerts} keyColumns={rule.key_columns} label={`Alerts of ${rule.name}`} />
        </TableCell>
      </TableRow>
    )}
    </>
  )
}
