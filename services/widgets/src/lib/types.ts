// The JSON shapes widgets receive, mirroring the backend's domain models
// (services/backend/src/ada/core/models). Only the fields widgets read are listed.

export type ColumnType = 'text' | 'integer' | 'number' | 'boolean' | 'date' | 'timestamp' | 'json'

export type Column = {
  name: string
  type: ColumnType
  nullable?: boolean
}

/** The columns of a period's first and last day; both inclusive. */
export type TimeRole = { start: string; end: string; grain?: 'year' | 'quarter' | 'month' | null }

/** The column of a region code, its code system and its level, e.g. "statfin" and
 * "wellbeing_services_county". Level "mixed" means several levels in one column. */
export type GeoRole = { code: string; system: string; level: string }

export type MeasureRole = {
  value: string
  lower?: string | null
  upper?: string | null
  suppressed?: string | null
  coverage?: string | null
}

export type Roles = {
  time?: TimeRole | null
  geo?: GeoRole | null
  measures?: MeasureRole[]
}

export type Widget = {
  id: string
  project_id: string
  session_id?: string | null
  operator_id: string
  type: string
  title: string
  spec: Record<string, unknown>
  note: string
}

export type WidgetData = {
  widget_id: string
  run_id: string
  /** The operator's declared output: what the columns mean. */
  output: Schema
  columns: Column[]
  rows: unknown[][]
  truncated: boolean
  is_scenario: boolean
  is_stale: boolean
}

/** The part of an operator's output schema a widget reads. */
export type Schema = { columns: Column[]; roles?: Roles }
