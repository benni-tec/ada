// Case types and cases (docs/contracts.md, "Cases"): a case type is a schema of fields, a
// case one instance of it under a key we set. Saving a case runs the automatic models on
// its type; any model on the type runs on request. Results are history on the case.

import { queryOptions, type QueryClient } from '@tanstack/react-query'

import { api, ApiFailure, type ApiError, type Schemas } from './client'
import type { Id } from './models'
import { statisticalModelKeys } from './statistical-models'

export type CaseType = Schemas['CaseType']
export type Field = Schemas['Field']
export type FieldType = Schemas['FieldType']
export type Case = Schemas['Case']
export type CaseEvent = Schemas['CaseEvent']
export type CaseState = Schemas['CaseState']
export type SavedCase = Schemas['SavedCase']
export type CaseResult = Schemas['CaseResult']
export type Section = Schemas['Section']
export type ModelOnCase = Schemas['ModelOnCase']
export type CaseWithResult = Schemas['CaseWithResult']
export type CaseWithResults = Schemas['CaseWithResults']
export type CaseValues = Record<string, unknown>

type Answer<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Answer<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok || data === undefined) {
    const body = error as ApiError | undefined
    throw new ApiFailure(response.status, typeof body?.detail === 'string' ? body : undefined)
  }
  return data
}

export const caseKeys = {
  types: (projectId: Id) => ['projects', projectId, 'case-types'] as const,
  type: (caseTypeId: Id) => ['case-types', caseTypeId] as const,
  cases: (caseTypeId: Id) => ['case-types', caseTypeId, 'cases'] as const,
  open: (caseTypeId: Id) => ['case-types', caseTypeId, 'open-cases'] as const,
  case: (caseTypeId: Id, key: string) => ['case-types', caseTypeId, 'case', key] as const,
  models: (caseTypeId: Id, key: string) => ['case-types', caseTypeId, 'case', key, 'models'] as const,
  modelCases: (modelId: Id) => ['models', modelId, 'cases'] as const,
}

export const listCaseTypes = (projectId: Id) =>
  unwrap(api.GET('/api/projects/{project_id}/case-types', { params: { path: { project_id: projectId } } }))

export const createCaseType = (projectId: Id, body: { name: string; description?: string; fields: Field[] }) =>
  unwrap(
    api.POST('/api/projects/{project_id}/case-types', {
      params: { path: { project_id: projectId } },
      body: { description: '', ...body },
    }),
  )

export const getCaseType = (caseTypeId: Id) =>
  unwrap(api.GET('/api/case-types/{case_type_id}', { params: { path: { case_type_id: caseTypeId } } }))

export const updateCaseType = (caseTypeId: Id, change: { name?: string; description?: string; fields?: Field[] }) =>
  unwrap(api.PATCH('/api/case-types/{case_type_id}', { params: { path: { case_type_id: caseTypeId } }, body: change }))

export const listCases = (caseTypeId: Id) =>
  unwrap(api.GET('/api/case-types/{case_type_id}/cases', { params: { path: { case_type_id: caseTypeId } } }))

export const listOpenCases = (caseTypeId: Id) =>
  unwrap(api.GET('/api/case-types/{case_type_id}/open-cases', { params: { path: { case_type_id: caseTypeId } } }))

export const getCase = (caseTypeId: Id, key: string) =>
  unwrap(api.GET('/api/case-types/{case_type_id}/cases/{key}', { params: { path: { case_type_id: caseTypeId, key } } }))

/** Creates or updates the case under `key`; the automatic models run on it. */
export const putCase = (caseTypeId: Id, key: string, values: CaseValues) =>
  unwrap(
    api.PUT('/api/case-types/{case_type_id}/cases/{key}', {
      params: { path: { case_type_id: caseTypeId, key } },
      body: { values },
    }),
  )

export const caseModels = (caseTypeId: Id, key: string) =>
  unwrap(
    api.GET('/api/case-types/{case_type_id}/cases/{key}/models', { params: { path: { case_type_id: caseTypeId, key } } }),
  )

/** Runs one model on the case and stores its result. */
export const evaluateCase = (caseTypeId: Id, key: string, modelId: Id) =>
  unwrap(
    api.POST('/api/case-types/{case_type_id}/cases/{key}/evaluate', {
      params: { path: { case_type_id: caseTypeId, key } },
      body: { model_id: modelId },
    }),
  )

/** Every case of the model's case type, with the model's latest result or none. */
export const modelCases = (modelId: Id) =>
  unwrap(api.GET('/api/models/{model_id}/cases', { params: { path: { model_id: modelId } } }))

export const setModelCaseType = (modelId: Id, caseTypeId: Id | null, autoRun: boolean) =>
  unwrap(
    api.PUT('/api/models/{model_id}/case-type', {
      params: { path: { model_id: modelId } },
      body: { case_type_id: caseTypeId, auto_run: autoRun },
    }),
  )

export const caseTypesQuery = (projectId: Id) =>
  queryOptions({ queryKey: caseKeys.types(projectId), queryFn: () => listCaseTypes(projectId) })

export const caseTypeQuery = (caseTypeId: Id) =>
  queryOptions({ queryKey: caseKeys.type(caseTypeId), queryFn: () => getCaseType(caseTypeId) })

export const casesQuery = (caseTypeId: Id) =>
  queryOptions({ queryKey: caseKeys.cases(caseTypeId), queryFn: () => listCases(caseTypeId) })

export const openCasesQuery = (caseTypeId: Id) =>
  queryOptions({ queryKey: caseKeys.open(caseTypeId), queryFn: () => listOpenCases(caseTypeId) })

export const caseQuery = (caseTypeId: Id, key: string) =>
  queryOptions({ queryKey: caseKeys.case(caseTypeId, key), queryFn: () => getCase(caseTypeId, key) })

export const caseModelsQuery = (caseTypeId: Id, key: string) =>
  queryOptions({ queryKey: caseKeys.models(caseTypeId, key), queryFn: () => caseModels(caseTypeId, key) })

export const modelCasesQuery = (modelId: Id) =>
  queryOptions({ queryKey: caseKeys.modelCases(modelId), queryFn: () => modelCases(modelId) })

/** After a case was saved or evaluated: its own views, its type's lists, and the case
 * lists of every model (a save may have run any of them). */
export function invalidateCase(queryClient: QueryClient, caseTypeId: Id, key: string) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: caseKeys.case(caseTypeId, key) }),
    queryClient.invalidateQueries({ queryKey: caseKeys.cases(caseTypeId) }),
    queryClient.invalidateQueries({ queryKey: caseKeys.open(caseTypeId) }),
    queryClient.invalidateQueries({ queryKey: ['models'], predicate: (query) => query.queryKey[2] === 'cases' }),
  ])
}

/** After a case type changed: the type itself and the project's list. */
export function invalidateCaseType(queryClient: QueryClient, projectId: Id, caseTypeId: Id) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: caseKeys.type(caseTypeId) }),
    queryClient.invalidateQueries({ queryKey: caseKeys.types(projectId) }),
  ])
}

/** After a model moved to another case type or changed when it runs. */
export function invalidateModelCaseType(queryClient: QueryClient, projectId: Id, modelId: Id) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: statisticalModelKeys.model(modelId) }),
    queryClient.invalidateQueries({ queryKey: statisticalModelKeys.list(projectId) }),
    queryClient.invalidateQueries({ queryKey: caseKeys.modelCases(modelId) }),
    queryClient.invalidateQueries({ queryKey: ['case-types'] }),
  ])
}

/** The case type's own fields: the ones no model on it reads. None are marked while no
 * model is on the type. */
export function ownFields(caseType: CaseType, models: readonly { reads: readonly string[] }[]): Set<string> {
  if (models.length === 0) return new Set()
  const read = new Set(models.flatMap((m) => m.reads))
  return new Set(caseType.fields.map((f) => f.name).filter((name) => !read.has(name)))
}

const urgency = { urgent: 0, warn: 1, info: 2, ok: 3 } as const

/** The result that most needs someone, whatever model made it: by status, then the most
 * overdue, then the soonest due, then the newest. Never by survival. */
export function mostUrgent(results: readonly (CaseResult | null | undefined)[]): CaseResult | undefined {
  const rank = (r: CaseResult) => [
    urgency[r.section.status],
    -(r.section.attention.overdue_by ?? 0),
    r.section.attention.due_in ?? Number.MAX_SAFE_INTEGER,
  ]
  return results
    .filter((r): r is CaseResult => r != null)
    .sort((a, b) => {
      const [x, y] = [rank(a), rank(b)]
      for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] - y[i]
      return b.created_at.localeCompare(a.created_at)
    })[0]
}

/** "Patient pathway model ran automatically.", after a save. */
export function ranText(names: readonly string[]): string {
  if (names.length === 0) return 'No model runs automatically on this case type.'
  const list = names.length === 1 ? names[0] : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`
  return `${list} ran automatically.`
}

/** The name the pages use for a field. */
export const fieldLabel = (field: Field) => field.label || field.name.replaceAll('_', ' ')

/** A level as words: "public_health_centre" reads "Public health centre", "60-69" "60–69". */
export function levelLabel(level: string) {
  if (/^\d+[-_]\d+$/.test(level)) return level.replace(/[-_]/, '–')
  const words = level.replaceAll('_', ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}
