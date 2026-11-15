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
  /** Further operators it reads by name, besides its own ("main"). */
  inputs?: Record<string, string>
  /** What went wrong the last time it was drawn, as its frame reported it; null when it drew. */
  render_error?: string | null
}

/** The name of a widget's own operator among its inputs. */
export const MAIN_INPUT = 'main'

export type WidgetData = {
  widget_id: string
  run_id: string
  /** Which of the widget's inputs this is ("main": its own operator). */
  input?: string
  /** The operator's declared output: what the columns mean. */
  output: Schema
  columns: Column[]
  rows: unknown[][]
  truncated: boolean
  /** The run binds at least one input slot to another operator (a pipeline composed into a
   * DAG). The name is historical: widgets do not mark it. */
  is_scenario: boolean
  /** A source behind the rows could not be refreshed: these are its last good data. */
  is_stale: boolean
  /** The sources behind the rows, as the run read them. */
  sources?: WidgetSource[]
}

export type WidgetSource = { operator_id: string; name: string; address: string; fetched_at?: string | null }

/** The part of an operator's output schema a widget reads. */
export type Schema = { columns: Column[]; roles?: Roles }
