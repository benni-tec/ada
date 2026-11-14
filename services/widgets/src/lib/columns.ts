// Reading rows by column name and roles. Rows arrive as tuples in the order of `columns`.

import type { Column, MeasureRole, Roles, WidgetData } from './types'

export const NUMERIC_TYPES = new Set(['integer', 'number'])
export const TIME_TYPES = new Set(['date', 'timestamp'])

/** A text setting of the spec, or undefined when it is missing or not text. */
export function specText(spec: Record<string, unknown>, key: string): string | undefined {
  const value = spec[key]
  return typeof value === 'string' && value !== '' ? value : undefined
}

/** Looks up a column by name; -1 when the data has no such column. */
export function columnIndex(data: WidgetData, name: string | null | undefined): number {
  return name ? data.columns.findIndex((column) => column.name === name) : -1
}

export function firstColumn(columns: Column[], types: Set<string>, except?: string): Column | undefined {
  return columns.find((column) => types.has(column.type) && column.name !== except)
}

/** The measure role describing a value column, if the schema declares one. */
export function measureFor(roles: Roles, column: string | undefined): MeasureRole | undefined {
  return roles.measures?.find((measure) => measure.value === column)
}

export function toNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

/** Suppression columns are booleans, but sources sometimes send 0/1 or "true". */
export function isTruthy(value: unknown): boolean {
  return value === true || value === 1 || value === 'true' || value === '1'
}

/** A boolean accessor for the measure's suppression flag; always false without one. */
export function suppressedAt(data: WidgetData, measure: MeasureRole | undefined): (row: unknown[]) => boolean {
  const index = columnIndex(data, measure?.suppressed)
  return index < 0 ? () => false : (row) => isTruthy(row[index])
}

export function formatNumber(value: number, decimals?: number): string {
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: decimals ?? (Math.abs(value) >= 100 ? 0 : 2),
    minimumFractionDigits: decimals ?? 0,
  }).format(value)
}

/** Compact tick labels: 1.2K, 3M. */
export function formatTick(value: number): string {
  return new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

/** How a number is written, as a spec names it: `integer` rounds to whole numbers,
 * `number` keeps up to `decimals` places, `percent` adds a percent sign to a value that is
 * already in percent (72.5 → "72.5 %"), `plain` writes it as it is, without thousands
 * separators (years, codes). */
export type NumberFormat = 'integer' | 'number' | 'percent' | 'plain'

const NUMBER_FORMATS: readonly string[] = ['integer', 'number', 'percent', 'plain']

export function isNumberFormat(value: unknown): value is NumberFormat {
  return typeof value === 'string' && NUMBER_FORMATS.includes(value)
}

/** A year is a label, not an amount: no thousands separator. */
export function isYearName(name: string): boolean {
  const lower = name.toLowerCase()
  return lower === 'year' || lower.endsWith('_year')
}

/** Columns whose numbers are written without separators: integer years (`year`,
 * `*_year`) and the time role's columns. */
export function isPlainColumn(column: Column, roles?: Roles): boolean {
  if (column.type === 'integer' && isYearName(column.name)) return true
  const time = roles?.time
  return !!time && (column.name === time.start || column.name === time.end)
}

export function formatAs(value: number, format: NumberFormat | undefined, decimals?: number): string {
  switch (format) {
    case 'plain':
      return String(value)
    case 'integer':
      return formatNumber(Math.round(value), 0)
    case 'percent':
      return `${formatNumber(value, decimals)} %`
    default:
      return formatNumber(value, decimals)
  }
}

/** "+1,346", "−210" or "±0": a difference always says which way it goes. */
export function signed(difference: number, write: (value: number) => string): string {
  const text = write(Math.abs(difference))
  if (text === write(0)) return `±${text}`
  return `${difference > 0 ? '+' : '−'}${text}`
}

/** The format a column is written in: the spec's, else plain for years and the time
 * role's columns, else the usual number. */
export function columnFormat(column: Column, roles?: Roles, format?: NumberFormat): NumberFormat | undefined {
  return format ?? (isPlainColumn(column, roles) ? 'plain' : undefined)
}

export function formatCell(
  value: unknown,
  column: Column,
  options: { roles?: Roles; format?: NumberFormat; decimals?: number } = {},
): string {
  if (value === null || value === undefined) return '–'
  if (NUMERIC_TYPES.has(column.type)) {
    const number = toNumber(value)
    if (number === null) return String(value)
    const format = columnFormat(column, options.roles, options.format)
    // Decimals are for fractions: an integer column keeps whole numbers unless its format says otherwise.
    const decimals = format === undefined && column.type === 'integer' ? undefined : options.decimals
    return formatAs(number, format, decimals)
  }
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/** One row per key: the row of the latest period, by the time role's end column. ISO
 * dates compare as strings; a row without a period loses to any row with one. Without a
 * time role (endIndex < 0) the last row of each key wins. Keys keep their first order. */
export function latestPerKey(rows: unknown[][], keyIndex: number, endIndex: number): Map<string, unknown[]> {
  const latest = new Map<string, unknown[]>()
  for (const row of rows) {
    const key = String(row[keyIndex] ?? '')
    const current = latest.get(key)
    const later =
      !current ||
      endIndex < 0 ||
      (row[endIndex] != null && (current[endIndex] == null || String(row[endIndex]) >= String(current[endIndex])))
    if (later) latest.set(key, row)
  }
  return latest
}

/** A period as people say it: "2024", "2022–2024", or both dates when it is not whole
 * years. Both ends are inclusive, as in the backend's Interval. */
export function formatPeriod(start: unknown, end: unknown): string | null {
  if (typeof start !== 'string' || typeof end !== 'string') return null
  const wholeYears = /^\d{4}-01-01/.test(start) && /^\d{4}-12-31/.test(end)
  if (wholeYears) {
    const [from, to] = [start.slice(0, 4), end.slice(0, 4)]
    return from === to ? from : `${from}–${to}`
  }
  return start === end ? start : `${start} – ${end}`
}
