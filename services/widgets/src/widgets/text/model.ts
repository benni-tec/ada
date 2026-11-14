// The text widget's placeholders: reading them out of the Markdown, and resolving each to
// what it shows from its input's data. The backend checks the same grammar when the widget
// is created, and resolves it the same way for the judge
// (services/backend/src/ada/core/services/widgets/text.py); this only renders.

import {
  columnIndex,
  formatAs,
  formatCell,
  isTruthy,
  measureFor,
  NUMERIC_TYPES,
  signed,
  toNumber,
} from '@/lib/columns'
import type { InputResult } from '@/lib/host'
import type { Column, Roles, WidgetData } from '@/lib/types'

export const FORMATS = ['integer', 'number1', 'percent', 'plain', 'signed1'] as const
export type TextFormat = (typeof FORMATS)[number]

/** The most rows `{{input}}` shows. */
export const TABLE_ROWS = 50

/**
 * One `{{…}}`:
 * - `{{gap.value}}`: the column `value` of input `gap`, from the latest period when the
 *   input has a time role, otherwise from its single row;
 * - `{{gap.value:percent}}`: the same, in one of FORMATS;
 * - `{{gap.value[county=Kainuu]}}` (and `…[county=Kainuu]:percent`): from the row where
 *   `county` is `Kainuu`; filters chain (`[county=Kainuu][sex=total]`);
 * - `{{gap}}`: the whole input as a compact table.
 */
export type Placeholder = {
  /** As written, braces included. */
  source: string
  input: string
  column?: string
  /** Rows kept: those where each column's value, as text, is the one given. */
  where: { column: string; value: string }[]
  /** As written; an unknown one resolves to an error. */
  format?: string
}

/** Either text to leave as it is, or a placeholder. */
export type Piece = string | Placeholder

// `\{{` is an escape, matched first so it is never the start of a placeholder.
const PLACEHOLDER =
  /\\\{\{|\{\{\s*([a-z][a-z0-9_]{0,31})(?:\.([A-Za-z_][A-Za-z0-9_]*)((?:\[[A-Za-z_][A-Za-z0-9_]*=[^\]\n{}]+\])*)(?::([a-z0-9]+))?)?\s*\}\}/g
const FILTER = /\[([A-Za-z_][A-Za-z0-9_]*)=([^\]]+)\]/g

/** The Markdown split into text and placeholders. An escaped `\{{` stays in the text as
 * it is, where Markdown turns it into `{{`; braces that are not a placeholder stay too. */
export function parse(markdown: string): Piece[] {
  const pieces: Piece[] = []
  let text = ''
  let last = 0
  for (const match of markdown.matchAll(PLACEHOLDER)) {
    if (match[0] === '\\{{') continue
    text += markdown.slice(last, match.index)
    if (text) pieces.push(text)
    text = ''
    const [source, input, column, filters, format] = match
    pieces.push({
      source,
      input,
      ...(column !== undefined && { column }),
      where: [...(filters ?? '').matchAll(FILTER)].map(([, name, value]) => ({ column: name, value: value.trim() })),
      ...(format !== undefined && { format }),
    })
    last = match.index + source.length
  }
  text += markdown.slice(last)
  if (text) pieces.push(text)
  return pieces
}

/** The inputs the placeholders read, in order of first use. */
export function inputsOf(pieces: readonly Piece[]): string[] {
  return [...new Set(pieces.filter((piece) => typeof piece !== 'string').map((piece) => piece.input))]
}

/** What a placeholder shows. */
export type Resolved =
  | { kind: 'value'; text: string; numeric: boolean }
  | { kind: 'table'; columns: Column[]; rows: string[][]; numeric: boolean[]; total: number; more: boolean }
  /** No value: `label` in place of it, `reason` in its tooltip. */
  | { kind: 'missing'; label: string; reason: string }

const missing = (reason: string, label = 'no value'): Resolved => ({ kind: 'missing', label, reason })

/** Resolves a placeholder against its input as the view read it. */
export function resolve(placeholder: Placeholder, result: InputResult | undefined): Resolved {
  if (!result) return missing(`The input "${placeholder.input}" was not read`)
  if (result.status === 'error') return missing(`The input "${placeholder.input}" cannot be read: ${result.message}`)
  const { data } = result
  const roles = data.output.roles ?? {}
  if (placeholder.column === undefined) return table(data, roles)
  return value(placeholder, placeholder.column, data, roles)
}

function table(data: WidgetData, roles: Roles): Resolved {
  const rows = data.rows.slice(0, TABLE_ROWS)
  return {
    kind: 'table',
    columns: data.columns,
    rows: rows.map((row) => data.columns.map((column, index) => formatCell(row[index], column, { roles }))),
    numeric: data.columns.map((column) => NUMERIC_TYPES.has(column.type)),
    total: data.rows.length,
    more: data.truncated || data.rows.length > TABLE_ROWS,
  }
}

/** The one row a value comes from, or why there is none. */
function row(placeholder: Placeholder, data: WidgetData, roles: Roles): { row: unknown[] } | { reason: string } {
  const name = `"${placeholder.input}"`
  // Without every row, neither the latest period nor the only matching row is known.
  if (data.truncated) {
    return { reason: `The input ${name} has more than the ${data.rows.length} rows a widget reads` }
  }
  let rows = data.rows
  const where = placeholder.where
  for (const filter of where) {
    const index = columnIndex(data, filter.column)
    if (index < 0) return { reason: `The input ${name} has no column "${filter.column}"` }
    rows = rows.filter((candidate) => candidate[index] !== null && candidate[index] !== undefined && String(candidate[index]) === filter.value)
  }
  const condition = where.map((filter) => `${filter.column} = ${filter.value}`).join(' and ')
  if (where.length > 0 && rows.length === 0) return { reason: `The input ${name} has no row where ${condition}` }
  // The period is the time role's end, else its start.
  const end = columnIndex(data, roles.time?.end) >= 0 ? columnIndex(data, roles.time?.end) : columnIndex(data, roles.time?.start)
  if (end >= 0 && rows.length > 1) {
    // ISO dates compare as strings, so the latest period is the greatest end.
    const latest = rows.reduce<string | null>((max, candidate) => {
      const value = candidate[end]
      return value === null || value === undefined || (max !== null && String(value) <= max) ? max : String(value)
    }, null)
    rows = rows.filter((candidate) => latest !== null && String(candidate[end]) === latest)
  }
  if (rows.length === 0) return { reason: `The input ${name} has no rows` }
  if (rows.length > 1) {
    const scope = [end >= 0 && 'in the latest period', condition && `where ${condition}`]
      .filter(Boolean)
      .join(' ')
    return {
      reason: `The input ${name} has ${rows.length} rows${scope ? ` ${scope}` : ''}, and a value needs one: pick it with [column=value]`,
    }
  }
  return { row: rows[0] }
}

function value(placeholder: Placeholder, columnName: string, data: WidgetData, roles: Roles): Resolved {
  const index = columnIndex(data, columnName)
  if (index < 0) return missing(`The input "${placeholder.input}" has no column "${columnName}"`)
  const format = placeholder.format
  if (format !== undefined && !(FORMATS as readonly string[]).includes(format)) {
    return missing(`Unknown format "${format}"; use one of ${FORMATS.join(', ')}`)
  }
  const found = row(placeholder, data, roles)
  if ('reason' in found) return missing(found.reason)
  const column = data.columns[index]
  const suppressed = columnIndex(data, measureFor(roles, columnName)?.suppressed)
  if (suppressed >= 0 && isTruthy(found.row[suppressed])) {
    return missing('The value was withheld, e.g. for a small count', 'suppressed')
  }
  const raw = found.row[index]
  if (raw === null || raw === undefined) return missing(`The column "${columnName}" is empty in this row`)
  const numeric = NUMERIC_TYPES.has(column.type) || typeof raw === 'number'
  if (format === undefined) return { kind: 'value', text: formatCell(raw, column, { roles }), numeric }
  if (format === 'plain') return { kind: 'value', text: String(raw), numeric }
  const number = toNumber(raw)
  if (number === null) return missing(`The format ${format} needs a number; "${columnName}" is ${column.type}`)
  return { kind: 'value', text: formatted(number, format as TextFormat), numeric: true }
}

function formatted(number: number, format: TextFormat): string {
  switch (format) {
    case 'integer':
      return formatAs(number, 'integer')
    case 'number1':
      return formatAs(number, 'number', 1)
    // One decimal at most, as the judge reads it.
    case 'percent':
      return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(number)} %`
    case 'signed1':
      return signed(number, (value) => formatAs(value, 'number', 1))
    case 'plain':
      return String(number)
  }
}
