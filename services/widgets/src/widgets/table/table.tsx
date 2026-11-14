import { columnIndex, formatCell, isNumberFormat, isTruthy, NUMERIC_TYPES, type NumberFormat } from '@/lib/columns'
import type { Loaded } from '@/lib/runtime'

/** A spec setting that maps column names to something, keeping the entries that fit. */
function byColumn<T>(value: unknown, fits: (entry: unknown) => entry is T): Record<string, T> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return {}
  return Object.fromEntries(Object.entries(value).filter((entry): entry is [string, T] => fits(entry[1])))
}

const isText = (value: unknown): value is string => typeof value === 'string' && value !== ''

/**
 * Columns and rows, scrollable in both directions.
 *
 * Spec: `columns`, the names to show and their order (default: all); `labels`, a header
 * per column (`{column: "Header"}`); `format`, how a column's numbers are written
 * (`{column: "integer" | "number" | "percent" | "plain"}`) with `decimals` for number and
 * percent. Integer years and the time role's columns are plain unless the spec says
 * otherwise. A measure whose suppression flag is set shows "suppressed" instead of its value.
 */
export function Table({ widget, data, roles }: Loaded) {
  const spec = widget.spec
  const labels = byColumn(spec.labels, isText)
  const formats = byColumn<NumberFormat>(spec.format, isNumberFormat)
  const decimals = typeof spec.decimals === 'number' ? spec.decimals : undefined
  const wanted = Array.isArray(spec.columns)
    ? spec.columns.filter((name): name is string => typeof name === 'string')
    : []
  const shown = (wanted.length > 0 ? wanted : data.columns.map((column) => column.name))
    .map((name) => ({ name, index: columnIndex(data, name) }))
    .filter(({ index }) => index >= 0)
    .map(({ index }) => {
      const column = data.columns[index]
      const measure = roles.measures?.find((candidate) => candidate.value === column.name)
      return { column, index, suppressed: columnIndex(data, measure?.suppressed) }
    })

  return (
    <>
      {/* Focusable, so keyboard users can scroll a wide or long table. */}
      <div className="ada-table-scroll" tabIndex={0} role="region" aria-label={widget.title || 'Table'}>
        <table className="ada-table">
          <thead>
            <tr>
              {shown.map(({ column }) => (
                <th
                  key={column.name}
                  scope="col"
                  className={NUMERIC_TYPES.has(column.type) ? 'ada-numeric' : undefined}
                >
                  {labels[column.name] ?? column.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {shown.map(({ column, index, suppressed }) => {
                  const isSuppressed = suppressed >= 0 && isTruthy(row[suppressed])
                  const empty = isSuppressed || row[index] === null || row[index] === undefined
                  const classes = [NUMERIC_TYPES.has(column.type) && 'ada-numeric', empty && 'ada-empty']
                  return (
                    <td key={column.name} className={classes.filter(Boolean).join(' ') || undefined}>
                      {isSuppressed
                        ? 'suppressed'
                        : formatCell(row[index], column, { roles, format: formats[column.name], decimals })}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {data.rows.length === 0 && <p className="ada-note">No rows.</p>}
      </div>
      {data.truncated && (
        <p className="ada-note" role="note">
          Showing the first {data.rows.length} rows; there are more.
        </p>
      )}
    </>
  )
}
