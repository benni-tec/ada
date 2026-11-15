// Statistical models (docs/superpowers/plans/2026-11-14-statistical-models-implementation.md):
// a project's models, their versions, the population view, and evaluating one synthetic
// profile, which is computed and returned, never stored.

import { queryOptions } from '@tanstack/react-query'

import { api, ApiFailure, type ApiError, type Schemas } from './client'
import type { Id } from './models'

export type StatisticalModel = Schemas['StatisticalModel']
export type ModelVersion = Schemas['ModelVersion']
export type ModelSpec = Schemas['ModelSpec']
export type Compiled = Schemas['Compiled']
export type TrialMatcherSpec = Schemas['TrialMatcherSpec']
export type TrialCompiled = Schemas['TrialCompiled']
/** A version of the patient pathway model: the survival spec and its build. */
export type PathwayVersion = ModelVersion & { spec: ModelSpec; compiled: Compiled }
/** A version of a trial matcher: what it reads; it reads it whenever it runs. */
export type TrialVersion = ModelVersion & { spec: TrialMatcherSpec; compiled: TrialCompiled }

/** The kind a version is for; versions made before kinds were tagged are pathway ones. */
export const versionKind = (version: ModelVersion) => version.spec?.kind ?? 'patient_pathway'
export const isPathwayVersion = (version: ModelVersion): version is PathwayVersion =>
  versionKind(version) === 'patient_pathway'
export const isTrialVersion = (version: ModelVersion): version is TrialVersion =>
  versionKind(version) === 'trial_matcher'
export type Criterion = Schemas['Criterion']
export type TargetTime = Schemas['TargetTime']
export type Parameter = Schemas['Parameter']
export type EvidenceGrade = Schemas['EvidenceGrade']
export type PathwayStep = Schemas['PathwayStep']
export type EvaluationInputs = Schemas['EvaluationInputs']
export type Evaluation = Schemas['Evaluation']
export type Deadline = Schemas['Deadline']
export type PathwayRow = Schemas['PathwayRow']
export type Lever = Schemas['Lever']
export type PopulationFigure = Schemas['PopulationFigure']
export type StepTime = Schemas['StepTime']

type Answer<T> = { data?: T; error?: unknown; response: Response }

async function unwrap<T>(call: Promise<Answer<T>>): Promise<T> {
  const { data, error, response } = await call
  if (!response.ok || data === undefined) {
    const body = error as ApiError | undefined
    throw new ApiFailure(response.status, typeof body?.detail === 'string' ? body : undefined)
  }
  return data
}

export const statisticalModelKeys = {
  list: (projectId: Id) => ['projects', projectId, 'models'] as const,
  model: (id: Id) => ['models', id] as const,
  latest: (id: Id) => ['models', id, 'latest'] as const,
  population: (id: Id) => ['models', id, 'population'] as const,
  stepTimes: (id: Id) => ['models', id, 'step-times'] as const,
}

export const listStatisticalModels = (projectId: Id) =>
  unwrap(api.GET('/api/projects/{project_id}/models', { params: { path: { project_id: projectId } } }))

export const createPathwayModel = (projectId: Id) =>
  unwrap(api.POST('/api/projects/{project_id}/models/pathway', { params: { path: { project_id: projectId } } }))

export const getModel = (id: Id) => unwrap(api.GET('/api/models/{model_id}', { params: { path: { model_id: id } } }))

export const latestVersion = (id: Id) =>
  unwrap(api.GET('/api/models/{model_id}/versions/latest', { params: { path: { model_id: id } } }))

/** Evaluates `inputs` on the given version, so a newer version made elsewhere is not used
 * silently; without one, the latest. */
export const evaluateModel = (id: Id, inputs: EvaluationInputs, version?: number) =>
  unwrap(api.POST('/api/models/{model_id}/evaluate', { params: { path: { model_id: id } }, body: { inputs, version } }))

export const getPopulation = (id: Id) =>
  unwrap(api.GET('/api/models/{model_id}/population', { params: { path: { model_id: id } } }))

export const statisticalModelsQuery = (projectId: Id) =>
  queryOptions({ queryKey: statisticalModelKeys.list(projectId), queryFn: () => listStatisticalModels(projectId) })

export const statisticalModelQuery = (id: Id) =>
  queryOptions({ queryKey: statisticalModelKeys.model(id), queryFn: () => getModel(id) })

export const latestVersionQuery = (id: Id) =>
  queryOptions({ queryKey: statisticalModelKeys.latest(id), queryFn: () => latestVersion(id) })

/** Per site and step: the Nordic standard, the days expected in Finland without a
 * standardised pathway, Finland's published typical days, and the median of the model's cases. */
export async function getStepTimes(id: Id): Promise<StepTime[]> {
  return unwrap(api.GET('/api/models/{model_id}/step-times', { params: { path: { model_id: id } } }))
}

export const stepTimesQuery = (id: Id) =>
  queryOptions({ queryKey: statisticalModelKeys.stepTimes(id), queryFn: () => getStepTimes(id) })

export const populationQuery = (id: Id) =>
  queryOptions({ queryKey: statisticalModelKeys.population(id), queryFn: () => getPopulation(id) })

/** The steps in pathway order, with the words the pages use. */
export const pathwaySteps: readonly { step: PathwayStep; label: string }[] = [
  { step: 'symptoms_to_contact', label: 'Symptoms → first contact' },
  { step: 'contact_to_physician', label: 'First contact → physician' },
  { step: 'physician_to_imaging', label: 'Physician → imaging done' },
  { step: 'imaging_to_referral', label: 'Imaging → pathway referral' },
  { step: 'referral_to_specialist', label: 'Referral → first specialist visit' },
  { step: 'specialist_to_workup', label: 'First visit → work-up complete' },
  { step: 'workup_to_treatment', label: 'Work-up complete → treatment start' },
]

/** The words for each evidence grade, from the strongest down. */
export const gradeLabels: Record<EvidenceGrade, string> = {
  standard: 'national standard',
  meta_analysis: 'meta-analysis',
  cohort: 'one cohort',
  registry: 'registry',
  assumption: 'assumption',
}

/** A deadline's status as words, e.g. "overdue by 3 days". */
export const statusWords: Record<Deadline['status'], (by: number) => string> = {
  met: (by) => (by === 0 ? 'met on the day' : `met, ${by} days early`),
  late: (by) => `late by ${by} day${by === 1 ? '' : 's'}`,
  due: (by) => (by === 0 ? 'due today' : `due in ${by} day${by === 1 ? '' : 's'}`),
  overdue: (by) => `overdue by ${by} day${by === 1 ? '' : 's'}`,
  not_applicable: () => 'no standard time',
}
