import { useQuery } from '@tanstack/react-query'

import { ErrorNotice, Loading } from '@/components/notices'
import { operatorRowsQuery, type Id, type OperatorId } from '@/lib/api'
import { cell, cellText, isLong } from '@/lib/cells'

export const PREVIEW_ROWS = 50

/**
 * The operator's first rows in the card's run: the same cut the card shows. Reading them
 * may execute the operator in that run (fixing its snapshots), never in another one.
 */
export function RowsPreview({
  runId,
  operatorId,
  total,
}: {
  /** Null while the page is starting its run: nothing is read until it is there. */
  runId: Id | null
  operatorId: OperatorId
  /** How many rows there are, when a snapshot counted them. */
  total?: number | null
}) {
  const rows = useQuery({
    ...operatorRowsQuery(runId ?? '', operatorId, PREVIEW_ROWS),
    enabled: runId !== null,
  })
  if (runId === null) return <p className="px-3 py-2 text-sm text-neutral-500">Waiting for the page’s run…</p>
  if (rows.isPending) return <div className="px-3 py-2"><Loading what="the rows" /></div>
  if (rows.error) return <div className="px-3 py-2"><ErrorNotice error={rows.error} prefix="The rows cannot be read:" /></div>

  const { columns, rows: values, truncated } = rows.data
  const shown = values.length
  const note = truncated
    ? `First ${shown} of ${typeof total === 'number' ? total.toLocaleString() : 'more'} rows`
    : `${shown} row${shown === 1 ? '' : 's'}`
  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* The table's caption says the same to a screen reader. */}
      <p aria-hidden="true" className="px-3 py-1.5 text-xs text-neutral-600 dark:text-neutral-400">
        {note}
      </p>
      {/* Focusable so the keyboard can scroll a table wider or taller than its region. */}
      <div tabIndex={0} aria-label="Rows" role="region" className="min-h-0 flex-1 overflow-auto focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-blue-600">
        {columns.length === 0 ? (
          <p className="px-3 py-2 text-sm text-neutral-500">No columns.</p>
        ) : (
          <table className="w-full text-left text-xs">
            <caption className="sr-only">{note}</caption>
            <thead className="sticky top-0 bg-neutral-100 dark:bg-neutral-800">
              <tr>
                {columns.map((column) => (
                  <th key={column.name} scope="col" className="px-3 py-1 font-medium whitespace-nowrap">
                    {column.name}
                    <span className="ml-1 font-normal text-neutral-500 dark:text-neutral-400">{column.type}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {values.map((row, index) => (
                <tr key={index} className="border-t border-neutral-100 dark:border-neutral-800">
                  {row.map((value, column) => (
                    <td
                      key={column}
                      className="px-3 py-1 whitespace-nowrap tabular-nums"
                      title={isLong(value) ? cellText(value) : undefined}
                    >
                      {cell(value)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
