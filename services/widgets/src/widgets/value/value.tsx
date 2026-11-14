import {
  columnFormat,
  columnIndex,
  firstColumn,
  formatAs,
  formatPeriod,
  isNumberFormat,
  measureFor,
  NUMERIC_TYPES,
  signed,
  specText,
  suppressedAt,
  toNumber,
} from '@/lib/columns'
import type { Loaded } from '@/lib/runtime'

/**
 * A single number with its label.
 *
 * Spec: `column` (default: the first measure role, else the first numeric column),
 * `label` (default: the column name), `unit`, `decimals`, `format` ("integer", "number",
 * "percent" or "plain"; years are plain by default), `compare_to` (a column of the same
 * row, or a number), shown as "+1,346 against 11,970". Shows the latest period when the
 * schema has a time role, otherwise the last row.
 */
export function Value({ widget, data, roles }: Loaded) {
  const spec = widget.spec
  const column =
    specText(spec, 'column') ?? roles.measures?.[0]?.value ?? firstColumn(data.columns, NUMERIC_TYPES)?.name
  const index = columnIndex(data, column)
  const label = specText(spec, 'label') ?? column ?? widget.title
  const unit = specText(spec, 'unit')
  const decimals = typeof spec.decimals === 'number' ? spec.decimals : undefined
  const format = index < 0 ? undefined : columnFormat(data.columns[index], roles, isNumberFormat(spec.format) ? spec.format : undefined)
  const write = (number: number) => formatAs(number, format, decimals)
  const withUnit = (text: string) => (unit ? `${text} ${unit}` : text)

  if (index < 0 || data.rows.length === 0) {
    return (
      <figure className="ada-value">
        <div className="ada-value-number ada-muted">–</div>
        <figcaption className="ada-value-label">
          {index < 0 ? `No column ${column ? `"${column}"` : 'with a number'} in the data` : 'No rows'}
        </figcaption>
      </figure>
    )
  }

  const time = roles.time
  const start = columnIndex(data, time?.start)
  const end = columnIndex(data, time?.end)
  // ISO dates compare correctly as strings, so the latest period is the greatest end.
  const row =
    end >= 0
      ? data.rows.reduce((latest, candidate) => (String(candidate[end]) > String(latest[end]) ? candidate : latest))
      : data.rows[data.rows.length - 1]

  const measure = measureFor(roles, column)
  const suppressed = suppressedAt(data, measure)(row)
  const value = toNumber(row[index])
  const lower = toNumber(row[columnIndex(data, measure?.lower)])
  const upper = toNumber(row[columnIndex(data, measure?.upper)])
  const period = start >= 0 && end >= 0 ? formatPeriod(row[start], row[end]) : null
  const comparedTo =
    typeof spec.compare_to === 'number'
      ? spec.compare_to
      : typeof spec.compare_to === 'string'
        ? toNumber(row[columnIndex(data, spec.compare_to)])
        : null

  return (
    <figure className="ada-value">
      {suppressed ? (
        <div className="ada-value-number ada-muted" title="The value was withheld, e.g. for a small count">
          Suppressed
        </div>
      ) : (
        <div className="ada-value-number">
          {value === null ? '–' : write(value)}
          {unit && value !== null && <span className="ada-value-label"> {unit}</span>}
        </div>
      )}
      <figcaption className="ada-value-label">
        {label}
        {period && <span className="ada-muted"> · {period}</span>}
      </figcaption>
      {!suppressed && value !== null && comparedTo !== null && (
        <p className="ada-note">
          {withUnit(signed(value - comparedTo, write))} against {withUnit(write(comparedTo))}
        </p>
      )}
      {!suppressed && lower !== null && upper !== null && (
        <p className="ada-note">
          Interval {write(lower)} – {write(upper)}
        </p>
      )}
    </figure>
  )
}
