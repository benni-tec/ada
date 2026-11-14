// Region outlines and other long text would push the numbers out of view: cut them short,
// with the whole value in the cell's title.
const MAX_CELL = 60

/** The whole value as text, for a cell's title. */
export function cellText(value: unknown): string {
  return typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value)
}

/** Whether a value is cut short in a table cell. */
export function isLong(value: unknown): boolean {
  return value !== null && value !== undefined && cellText(value).length > MAX_CELL
}

/** A value as one table cell shows it: empty as a dash, long text cut short. */
export function cell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  const text = cellText(value)
  return text.length > MAX_CELL ? `${text.slice(0, MAX_CELL)}…` : text
}
