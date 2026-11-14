import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import type { Evaluation, ModelVersion, StatisticalModel } from '@/lib/api'

import { project, renderAt, serveApi, web } from './app'

// The models pages: the list with the banner every page carries, and one model's
// evaluation, which leads with the trigger and the deadlines.

const model: StatisticalModel = {
  id: 'm1',
  project_id: 'p1',
  name: 'Patient pathway model',
  description: 'Whether a presentation would start a Nordic fast-track pathway.',
  kind: 'patient_pathway',
  latest_version: 1,
  auto_run: false,
  created_by: web,
  created_at: '2026-11-14T10:00:00Z',
}

const provenance = { source: 'Helsedirektoratet 2026', passage: 'Forløpstider', grade: 'standard' as const, url: null, country: 'Norway' }

const version: ModelVersion = {
  id: 'v1',
  model_id: 'm1',
  version: 1,
  spec: {
    outcome: '5-year relative survival',
    structure: 'relative_survival_dag',
    sites: ['lung'],
    terms: [
      { name: 'sex', levels: ['female', 'male'], reference: 'female', display: 'patient' },
      { name: 'education', levels: ['basic', 'tertiary'], reference: 'tertiary', display: 'analyst' },
    ],
    criteria: [
      { id: 'lung_symptoms_smoker', site: 'lung', stage: 'suspicion', text: 'Cough for 6 weeks, smoker over 40', countries: ['Sweden'], provenance },
      { id: 'lung_imaging', site: 'lung', stage: 'well_founded', text: 'Imaging finding suggesting lung cancer', countries: ['Norway', 'Sweden'], provenance },
    ],
    targets: [{ site: 'lung', step: null, modality: 'surgery', days_by_country: { Norway: 42, Sweden: 44 }, provenance, other_sources: [] }],
    baseline: [{ site: 'lung', sex: 'female', age_band: null, stage: null, survival: 0.38, excess_share: null, provenance }],
    parameters: {},
    arrows: {},
    comparison: { country: 'Finland', survival: { 'lung:female': 0.308 }, days: { lung: { contact_to_physician: 14 } }, provenance, survival_by_education: {}, education_provenance: null },
    toggles: [{ name: 'finland_residual', label: 'Finland residual', default: true, about: 'What the days do not explain.' }],
    flags: [],
    intended_use: 'Educational use with synthetic profiles.',
    cautions: ['Survival is counted from diagnosis (lead time).'],
  },
  compiled: { targets: { lung: { pathway: { surgery: 43 } } }, parameters: {}, population: [], validation: [], warnings: [] },
  created_by: web,
  created_at: '2026-11-14T10:00:00Z',
}

const evaluation: Evaluation = {
  model_id: 'm1',
  version: 1,
  trigger: {
    suspicion: { stage: 'suspicion', fired: true, countries: ['Sweden'], criteria: ['Cough for 6 weeks, smoker over 40'] },
    well_founded: { stage: 'well_founded', fired: true, countries: ['Norway', 'Sweden'], criteria: ['Imaging finding suggesting lung cancer'] },
    clock_start: 27,
    note: 'This presentation would start a pathway in Norway and Sweden. Finland has no national trigger and no standard times.',
  },
  deadlines: [
    { label: 'Treatment start', rule: '43 days after the trigger', countries: ['Norway', 'Sweden'], due_day: 70, status: 'overdue', by: 1 },
  ],
  pathway: [
    { step: 'contact_to_physician', label: 'First contact → physician', days: 14, target: 7, gap: 7, countries: [], patient_interval: false, current: false },
  ],
  days_behind: 20,
  survival: { now: 30, on_target: 31, by_setting: { 'finland_residual=on': { now: 30, on_target: 31 } }, range_now: { low: 30, high: 37 }, range_on_target: { low: 31, high: 38 }, setting: { finland_residual: true } },
  levers: [{ step: 'workup_to_treatment', label: 'Work-up complete → treatment start', gain: 1, grade: 'cohort', text: 'Heiden 2021' }],
  flags: ['Offer a patient navigator to keep the next steps on time.'],
  warnings: ['Survival is counted from diagnosis (lead time).'],
  contributions: [],
}

function serve() {
  return serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/projects/p1/models': [model],
    'GET /api/projects/p1/case-types': [],
    'GET /api/models/m1': model,
    'GET /api/models/m1/versions/latest': version,
    'GET /api/models/m1/population': [],
    'POST /api/models/m1/evaluate': (body: unknown) => {
      const { inputs } = body as { inputs: { presentation: string[] } }
      expect(inputs.presentation).toEqual(['lung_symptoms_smoker', 'lung_imaging'])
      return evaluation
    },
  })
}

test('every page carries the data rule, and the list links to the model', async () => {
  serve()
  renderAt('/projects/p1/models')
  expect(await screen.findByRole('note')).toHaveTextContent('Educational use only. Do not enter patient data.')
  const link = await screen.findByRole('link', { name: 'Patient pathway model' })
  expect(link).toHaveAttribute('href', '/projects/p1/models/m1')
})

test('the evaluation leads with the trigger and the deadlines, then the days behind, then survival', async () => {
  serve()
  renderAt('/projects/p1/models/m1?view=evaluation')
  expect(await screen.findByRole('tab', { name: 'Evaluation' })).toHaveAttribute('aria-selected', 'true')
  fireEvent.click(screen.getByLabelText('Cough for 6 weeks, smoker over 40'))
  fireEvent.click(screen.getByLabelText('Imaging finding suggesting lung cancer'))
  fireEvent.click(screen.getByRole('button', { name: 'Evaluate' }))

  await waitFor(() => expect(screen.getByText(/would start a pathway in Norway and Sweden/)).toBeInTheDocument())
  const trigger = document.querySelector('[data-section="trigger"]') as HTMLElement
  expect(within(trigger).getByText('overdue by 1 day')).toBeInTheDocument()
  expect(within(trigger).getByText(/Next:/).closest('p')).toHaveTextContent('treatment start, overdue by 1 day')
  expect(screen.getByText('20 days behind target')).toBeInTheDocument()
  const survival = document.querySelector('[data-section="survival"]') as HTMLElement
  expect(within(survival).getByRole('button', { name: 'Finland residual' })).toHaveAttribute('aria-pressed', 'true')
  expect(within(survival).getByText('one cohort')).toBeInTheDocument()
  expect(screen.getByText('Offer a patient navigator to keep the next steps on time.')).toBeInTheDocument()
  expect(screen.getByText('Survival is counted from diagnosis (lead time).')).toBeInTheDocument()
})
