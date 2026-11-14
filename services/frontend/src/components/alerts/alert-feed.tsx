import { useQuery } from '@tanstack/react-query'
import { useId, useState } from 'react'

import { ErrorNotice, Loading } from '@/components/notices'
import { Time } from '@/components/provenance'
import { alertFeedQuery, alertRowsQuery, type AlertState, type AlertView, type Id } from '@/lib/api'

import { keyText } from './labels'
import { SeverityBadge } from './severity'

const filters: { state: AlertState | null; label: string }[] = [
  { state: null, label: 'All' },
  { state: 'firing', label: 'Firing' },
  { state: 'resolved', label: 'Resolved' },
]

const listClass =
  'divide-y divide-neutral-200 rounded-lg border border-neutral-200 dark:divide-neutral-800 dark:border-neutral-800'

/** The project's alerts, firing first and newest first within each state. */
export function AlertFeed({ projectId }: { projectId: Id }) {
  const [state, setState] = useState<AlertState | null>(null)
  const { data, error, isPending } = useQuery(alertFeedQuery(projectId, state))
  const headingId = useId()

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={headingId} className="text-lg font-semibold">
          Alert feed
        </h2>
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
      </div>
      {isPending ? (
        <Loading what="alerts" />
      ) : error ? (
        <ErrorNotice error={error} prefix="The alerts cannot be loaded:" />
      ) : data.length === 0 ? (
        <p className="text-sm text-neutral-500">
          {state === 'firing' ? 'Nothing is firing.' : state === 'resolved' ? 'No resolved alerts.' : 'No alerts yet.'}
        </p>
      ) : (
        <ul className={listClass} aria-label="Alerts">
          {data.map((view) => (
            <FeedItem key={view.alert.id} view={view} />
          ))}
        </ul>
      )}
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
 * The measure's rows for the alert's key, in the run that last showed the condition: the
 * alerting period and the history its time functions read. A run is a consistent cut, so
 * this is exactly the data the check saw.
 */
function AlertRows({ view }: { view: AlertView }) {
  const { alert, rule } = view
  const { data, error, isPending } = useQuery(alertRowsQuery(alert.last_run_id, rule.operator_id))
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
          Rows for {keyText(alert.key)} in run <span className="font-mono">{alert.last_run_id.slice(-8)}</span>
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
                <td key={column} className="px-2 py-1 tabular-nums">
                  {value === null ? '—' : String(value)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
