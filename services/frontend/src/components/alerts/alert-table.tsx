import { useQuery } from '@tanstack/react-query'
import { ChevronDown } from 'lucide-react'
import { useId, useState } from 'react'

import { IconButton } from '@/components/icon-action'
import { ErrorNotice, Loading } from '@/components/notices'
import { Time } from '@/components/provenance'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { alertRowsQuery, type AlertView } from '@/lib/api'
import { cell, cellText, isLong } from '@/lib/cells'

import { keyText, severityTextClasses } from './labels'

/** What the people reading it call an alert's state: it is active, or it has ended. */
const stateText = (view: AlertView) => (view.alert.state === 'firing' ? 'Active' : 'Ended')

/** A rule's alerts, one row per key it raised one for; each opens the data behind it. */
export function AlertTable({ views, label }: { views: AlertView[]; label: string }) {
  return (
    <Table aria-label={label}>
      <TableHeader>
        <TableRow>
          <TableHead>Key</TableHead>
          <TableHead>State</TableHead>
          <TableHead>When</TableHead>
          <TableHead>
            <span className="sr-only">Data</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {views.map((view) => (
          <AlertRow key={view.alert.id} view={view} />
        ))}
      </TableBody>
    </Table>
  )
}

function AlertRow({ view }: { view: AlertView }) {
  const { alert } = view
  const [open, setOpen] = useState(false)
  const rowsId = useId()
  const active = alert.state === 'firing'
  const label = open ? 'Hide the data' : active ? 'Show the data behind it' : 'Show the data it last showed on'
  return (
    <>
      <TableRow data-state={open ? 'selected' : undefined}>
        <TableCell className="font-medium">{keyText(alert.key)}</TableCell>
        <TableCell className={active ? severityTextClasses[view.rule.severity] : 'text-muted-foreground'}>
          {stateText(view)}
        </TableCell>
        <TableCell className="text-muted-foreground">
          {active ? 'Since ' : 'From '}
          <Time value={alert.started_at} />
          {alert.resolved_at && (
            <>
              {' to '}
              <Time value={alert.resolved_at} />
            </>
          )}
        </TableCell>
        <TableCell className="w-0 text-right">
          <IconButton label={label} aria-expanded={open} aria-controls={rowsId} onClick={() => setOpen(!open)}>
            <ChevronDown className={open ? 'rotate-180 transition-transform' : 'transition-transform'} />
          </IconButton>
        </TableCell>
      </TableRow>
      {open && (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={4} id={rowsId} className="bg-muted/30 whitespace-normal">
            <AlertRows view={view} />
          </TableCell>
        </TableRow>
      )}
    </>
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
          {alert.condition_sql ? 'The rows behind it' : 'Rows'} for {keyText(alert.key)} in run{' '}
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
