// TEMPORARY: hand-written mirrors of the backend's domain models
// (services/backend/src/ada/core/models), written while the routes did not exist yet.
// Integration replaces this file with the generated types (`moon run frontend:generate`,
// then `Schemas['Project']` and so on from ./client) and deletes it.

/** UUIDs as strings; operators are the exception, their id is their identity hash. */
export type Id = string
export type OperatorId = string
/** ISO 8601 date-time, as the API sends it. */
export type DateTime = string

export type ActorKind = 'user' | 'agent' | 'external_agent' | 'system'

export type Actor = {
  kind: ActorKind
  /** For an external agent, the client name it reported when connecting over MCP. */
  name: string
}

export type Project = {
  id: Id
  name: string
  created_at: DateTime
  revision: number
}

export type Session = {
  id: Id
  project_id: Id
  title: string
  origin_dashboard_id: Id | null
  /** The dashboard shown beside the conversation, if any. */
  panel_dashboard_id: Id | null
  created_at: DateTime
  revision: number
}

export type EntryKind = 'message' | 'operator' | 'widget'

export type SessionEntry = {
  id: Id
  session_id: Id
  kind: EntryKind
  /** The message text, or the calling agent's one-line reason for a tool call. */
  text: string
  /** The operator id or widget id the entry is about. */
  ref: string | null
  actor: Actor
  created_at: DateTime
}

export type ColumnType = 'text' | 'integer' | 'number' | 'boolean' | 'date' | 'timestamp' | 'json'

export type Column = { name: string; type: ColumnType; nullable: boolean }

export type MeasureRole = {
  value: string
  lower: string | null
  upper: string | null
  suppressed: string | null
  coverage: string | null
}

export type Roles = {
  time: { start: string; end: string } | null
  geo: { code: string; system: string; level: string } | null
  measures: MeasureRole[]
}

export type Schema = {
  kind: 'table' | 'document' | 'result'
  columns: Column[]
  roles: Roles
  derived: boolean
}

export type OperatorKind = 'source' | 'extract' | 'input' | 'transform' | 'statistic' | 'agent'

export type Operator = {
  id: OperatorId
  project_id: Id
  kind: OperatorKind
  params: Record<string, unknown>
  inputs: OperatorId[]
  output: Schema
  materializing: boolean
  created_by: Actor
  created_at: DateTime
}

export type AccessKind = 'url' | 'request' | 'browser' | 'document'
export type DataFormat = 'csv' | 'json' | 'parquet'
export type FreshnessKind = 'manual' | 'ttl' | 'probe' | 'push'

export type DataSource = {
  id: Id
  project_id: Id
  name: string
  access_kind: AccessKind
  address: string
  format: DataFormat
  options: Record<string, unknown>
  freshness: {
    kind: FreshnessKind
    ttl_seconds: number | null
    latest_period_ttl_seconds: number | null
  }
  declared_schema: Schema | null
  created_at: DateTime
  last_checked_at: DateTime | null
  last_probe_token: string | null
  /** Why the last refresh failed; while set, widgets on this source show stale data. */
  last_error: string | null
  revision: number
}

export type Widget = {
  id: Id
  project_id: Id
  session_id: Id | null
  operator_id: OperatorId
  /** Which widget bundle renders it, e.g. "value", "table", "line-chart". */
  type: string
  title: string
  spec: Record<string, unknown>
  /** The calling agent's one-line reason, shown in the card header. */
  note: string
  created_by: Actor
  created_at: DateTime
}

export type EventType =
  | 'session.entry_added'
  | 'widget.created'
  | 'run.started'
  | 'run.finished'
  | 'run.failed'
  | 'source.refreshed'
  | 'source.refresh_failed'
  | 'dashboard.changed'
  | 'report.version_created'
  | 'alert.firing'
  | 'alert.resolved'

/** One message of the live stream. The payload carries ids only. */
export type LiveEvent = {
  type: EventType
  project_id: Id
  payload: Record<string, unknown>
  at: DateTime
}
