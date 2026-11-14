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

export function formatCell(value: unknown, column: Column): string {
  if (value === null || value === undefined) return '–'
  if (NUMERIC_TYPES.has(column.type)) {
    const number = toNumber(value)
    return number === null ? String(value) : formatNumber(number)
  }
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
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
