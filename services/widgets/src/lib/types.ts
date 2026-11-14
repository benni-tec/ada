// The JSON shapes widgets receive, mirroring the backend's domain models
// (services/backend/src/ada/core/models). Only the fields widgets read are listed.

export type ColumnType = 'text' | 'integer' | 'number' | 'boolean' | 'date' | 'timestamp' | 'json'

export type Column = {
  name: string
  type: ColumnType
  nullable?: boolean
}

export type TimeRole = { start: string; end: string }

export type MeasureRole = {
  value: string
  lower?: string | null
  upper?: string | null
  suppressed?: string | null
  coverage?: string | null
}

export type Roles = {
  time?: TimeRole | null
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
  columns: Column[]
  rows: unknown[][]
  truncated: boolean
  is_scenario: boolean
  is_stale: boolean
}

/** The part of an operator a widget reads: what its output columns mean. */
export type Operator = {
  id: string
  output: { columns: Column[]; roles?: Roles }
}
