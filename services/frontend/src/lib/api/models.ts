// The domain models as the API sends them, generated from the backend's OpenAPI schema
// (`moon run frontend:generate`). Named here so components import one name per model.

import type { Context } from './agent'
import type { Schemas } from './client'

/** UUIDs as strings; operators are the exception, their id is their identity hash. */
export type Id = string
export type OperatorId = string
/** ISO 8601 date-time, as the API sends it. */
export type DateTime = string

export type Actor = Schemas['Actor']
export type ActorKind = Schemas['ActorKind']
export type Project = Schemas['Project']
export type Session = Schemas['Session']
// TEMPORARY, wave 3 (docs/contracts/wave3.md): an entry may be an agent turn, and carries
// the message's context. Integration regenerates the schema with both.
export type EntryKind = Schemas['EntryKind'] | 'agent_turn'
export type SessionEntry = Omit<Schemas['SessionEntry'], 'kind'> & { kind: EntryKind; context?: Context[] }
export type Column = Schemas['Column']
export type ColumnType = Schemas['ColumnType']
export type MeasureRole = Schemas['MeasureRole']
export type Roles = Schemas['Roles']
export type Schema = Schemas['Schema']
export type OperatorKind = Schemas['OperatorKind']
export type Operator = Schemas['Operator']
export type AccessKind = Schemas['AccessKind']
export type DataFormat = Schemas['DataFormat']
export type DataSource = Schemas['DataSource']
// TEMPORARY, wave 3: a widget pinned to a dashboard is a copy, pointing at its original.
export type Widget = Schemas['Widget'] & { copied_from?: Id | null }
export type WidgetData = Schemas['WidgetData']

// The live stream is not described by the OpenAPI schema, so its two types are written
// out here; they mirror services/backend/src/ada/core/models/events.py.

export type EventType =
  | 'session.created'
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
  // TEMPORARY, wave 3 (docs/contracts/wave3.md); not in the backend's events.py yet.
  | 'agent.turn_started'
  | 'agent.turn_part'
  | 'agent.turn_finished'

/** One message of the live stream. The payload carries ids only, except a turn's part. */
export type LiveEvent = {
  type: EventType
  project_id: Id
  payload: Record<string, unknown>
  at: DateTime
}
