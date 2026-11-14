// Judges (docs/superpowers/plans/2026-11-14-text-widget-and-judges.md, task 4): the global
// defaults per kind, a project's overrides, the verdicts on widgets, and reviewing again.

import { queryOptions } from '@tanstack/react-query'

import { api, ApiFailure, type ApiError, type Schemas } from './client'
import type { Id, Widget } from './models'

export type JudgeKind = Schemas['JudgeKind']
export type Strictness = Schemas['Strictness']
export type Outcome = Schemas['Outcome']
export type Verdict = Schemas['Verdict']
export type Finding = Schemas['Finding']
/** One kind's settings for every project. */
export type JudgeDefaults = Schemas['JudgeDefaults']
/** What review uses in a project: the defaults with its overrides; `overridden` names them. */
export type JudgeSettings = Schemas['JudgeSettings']
/** Fields left out stay; `model_id: null` clears the model. */
export type JudgeDefaultsChange = Schemas['JudgeDefaultsChange']
/** Fields left out stay; `null` inherits the global default again. */
export type JudgeOverrideChange = Schemas['JudgeOverrideChange']

/** The kinds in the order the settings show them, with what each judges. */
export const judgeKinds: readonly { kind: JudgeKind; label: string; about: string }[] = [
  {
    kind: 'text_widget',
    label: 'Text widgets',
    about: 'Reads a text widget’s Markdown with its values, and flags figures no input backs and claims its data contradicts.',
  },
  {
    kind: 'widget_code',
    label: 'Custom widget code',
    about: 'Reads a custom widget’s code, and flags data written into it that should come from its inputs.',
  },
]

/** The settings' words for each strictness, and what it does. */
export const strictnesses: readonly { value: Strictness; label: string; does: string }[] = [
  { value: 'off', label: 'Off', does: 'Never reviewed: widgets say “Not reviewed”.' },
  { value: 'warn', label: 'Warn', does: 'Reviewed, and findings are shown on the widget; nothing is stopped.' },
  { value: 'block', label: 'Block', does: 'Reviewed; a failed review also stops a report version from being saved.' },
]

/** The settings fields a project can override. */
export type JudgeField = 'strictness' | 'model_id' | 'instructions'

type Answer<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Answer<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok || data === undefined) {
    const body = error as ApiError | undefined
    throw new ApiFailure(response.status, typeof body?.detail === 'string' ? body : undefined)
  }
  return data
}

export const getJudgeDefaults = () => unwrap(api.GET('/api/settings/judges'))

export const setJudgeDefaults = (kind: JudgeKind, change: JudgeDefaultsChange) =>
  unwrap(api.PUT('/api/settings/judges/{kind}', { params: { path: { kind } }, body: change }))

export const getProjectJudges = (projectId: Id) =>
  unwrap(api.GET('/api/projects/{project_id}/judges', { params: { path: { project_id: projectId } } }))

export const overrideProjectJudge = (projectId: Id, kind: JudgeKind, change: JudgeOverrideChange) =>
  unwrap(
    api.PUT('/api/projects/{project_id}/judges/{kind}', {
      params: { path: { project_id: projectId, kind } },
      body: change,
    }),
  )

/** The project's widgets with a verdict of this kind, newest verdict first. */
export const listVerdicts = (projectId: Id, kind: JudgeKind): Promise<Widget[]> =>
  unwrap(api.GET('/api/projects/{project_id}/verdicts', { params: { path: { project_id: projectId }, query: { kind } } }))

/** Reviews the widget now, in the run given (else the latest), and returns it with its verdict. */
export const reviewWidget = (widgetId: Id, runId?: Id | null): Promise<Widget> =>
  unwrap(
    api.POST('/api/widgets/{widget_id}/review', {
      params: { path: { widget_id: widgetId }, query: runId ? { run_id: runId } : {} },
    }),
  )

export const judgeKeys = {
  defaults: () => ['settings', 'judges'] as const,
  project: (projectId: Id) => ['projects', projectId, 'judges'] as const,
  /** Every verdict list of the project: a widget's change can change any of them. */
  verdicts: (projectId: Id) => ['projects', projectId, 'verdicts'] as const,
  verdictsOf: (projectId: Id, kind: JudgeKind) => ['projects', projectId, 'verdicts', kind] as const,
}

export const judgeDefaultsQuery = () => queryOptions({ queryKey: judgeKeys.defaults(), queryFn: getJudgeDefaults })

export const projectJudgesQuery = (projectId: Id) =>
  queryOptions({ queryKey: judgeKeys.project(projectId), queryFn: () => getProjectJudges(projectId) })

export const verdictsQuery = (projectId: Id, kind: JudgeKind) =>
  queryOptions({ queryKey: judgeKeys.verdictsOf(projectId, kind), queryFn: () => listVerdicts(projectId, kind) })

/**
 * A project's own instructions for a kind. The effective text is the global one, then the
 * project's, joined by a blank line, and the API does not send the project's part alone,
 * so it is what follows the global text.
 */
export function projectInstructions(effective: JudgeSettings, defaults: JudgeDefaults | undefined): string {
  if (!effective.overridden.includes('instructions')) return ''
  const global = defaults?.instructions.trim() ?? ''
  if (!global) return effective.instructions
  return effective.instructions.startsWith(global) ? effective.instructions.slice(global.length).replace(/^\n+/, '') : effective.instructions
}
