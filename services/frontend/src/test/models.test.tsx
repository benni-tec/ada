import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import type { Evaluation, ModelVersion, PopulationFigure, StatisticalModel } from '@/lib/api'

import { json, project, renderAt, serveApi, web } from './app'

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
    kind: 'patient_pathway',
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
    targets: [
      { site: 'lung', step: null, modality: 'surgery', days_by_country: { Norway: 42, Sweden: 44 }, provenance, other_sources: [] },
      { site: 'colorectal', step: null, modality: 'surgery', days_by_country: { Norway: 35, Sweden: 37 }, provenance, other_sources: [] },
    ],
    baseline: [{ site: 'lung', sex: 'female', age_band: null, stage: null, survival: 0.38, excess_share: null, provenance }],
    parameters: {},
    arrows: {},
    comparison: { country: 'Finland', survival: { 'lung:female': 0.308 }, days: { lung: { contact_to_physician: 14 }, colorectal: { contact_to_physician: 10 } }, provenance, survival_by_education: {}, education_provenance: null },
    toggles: [{ name: 'finland_residual', label: 'Finland residual', default: true, about: 'What the days do not explain.' }],
    flags: [],
    intended_use: 'Educational use with synthetic profiles.',
    cautions: ['Survival is counted from diagnosis (lead time).'],
  },
  compiled: { kind: 'patient_pathway', targets: { lung: { pathway: { surgery: 43 } }, colorectal: { pathway: { surgery: 36 } } }, parameters: {}, population: [], validation: [], warnings: [] },
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

const figure: PopulationFigure = { site: 'lung', sex: 'female', baseline: 38, timing_adjusted: 36, observed: 31, residual: 1.2, note: 'Two of the seven points.' }

const bodies: unknown[] = []

function serve(overrides: Record<string, unknown> = {}) {
  bodies.length = 0
  return serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/projects/p1/models': [model],
    'GET /api/projects/p1/case-types': [],
    'GET /api/models/m1': model,
    'GET /api/models/m1/versions/latest': version,
    'GET /api/models/m1/population': [figure],
    'POST /api/models/m1/evaluate': (body: unknown) => {
      bodies.push(body)
      return evaluation
    },
    ...overrides,
  })
}

const failure = () => json({ detail: 'The model store is down.' }, 500)

async function evaluateProfile() {
  renderAt('/projects/p1/models/m1?view=evaluation')
  expect(await screen.findByRole('tab', { name: 'Evaluation' })).toHaveAttribute('aria-selected', 'true')
  fireEvent.click(screen.getByLabelText('Cough for 6 weeks, smoker over 40'))
  fireEvent.click(screen.getByLabelText('Imaging finding suggesting lung cancer'))
  fireEvent.click(screen.getByRole('button', { name: 'Evaluate' }))
  await waitFor(() => expect(screen.getByText(/would start a pathway in Norway and Sweden/)).toBeInTheDocument())
}

test('the list links to the model', async () => {
  serve()
  renderAt('/projects/p1/models')
  const link = await screen.findByRole('link', { name: 'Patient pathway model' })
  expect(link).toHaveAttribute('href', '/projects/p1/models/m1')
})

test('the models list says so when it cannot be loaded', async () => {
  serve({ 'GET /api/projects/p1/models': failure })
  renderAt('/projects/p1/models')
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the models: The model store is down.')
  expect(screen.queryByRole('table')).not.toBeInTheDocument()
})

test('the model page says so when the model or its latest version cannot be loaded', async () => {
  serve({ 'GET /api/models/m1/versions/latest': failure })
  renderAt('/projects/p1/models/m1?view=evaluation')
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the model: The model store is down.')
  expect(screen.queryByText(/Loading/)).not.toBeInTheDocument()
})

test('the evaluation leads with the trigger and the deadlines, then the days behind, then survival', async () => {
  serve()
  await evaluateProfile()
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

test('the evaluation sends the version the page shows, and says the survival figures are relative', async () => {
  serve()
  await evaluateProfile()
  expect(bodies).toEqual([
    expect.objectContaining({ version: 1, inputs: expect.objectContaining({ presentation: ['lung_symptoms_smoker', 'lung_imaging'] }) }),
  ])
  const survival = document.querySelector('[data-section="survival"]') as HTMLElement
  expect(within(survival).getByRole('heading', { name: '5-year relative survival' })).toBeInTheDocument()
  expect(within(survival).getByText(/same age and sex without cancer/)).toBeInTheDocument()
  expect(within(survival).getByRole('img', { name: '5-year relative survival 30 per 100, as it stands' })).toBeInTheDocument()
  expect(within(survival).getByText(/As it stands: 30–37 per 100/)).toBeInTheDocument()
  expect(survival).not.toHaveTextContent(/alive/i)
})

test('a result stays with the profile it was computed from, and is marked when the form changes', async () => {
  serve()
  await evaluateProfile()
  expect(screen.queryByText(/The profile has changed/)).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Days in step 2'), { target: { value: '30' } })
  expect(screen.getByText(/The profile has changed since this result/)).toHaveAttribute('role', 'status')

  // A setting re-evaluates the profile the result was computed from, not the edited form.
  fireEvent.click(screen.getByRole('button', { name: 'Finland residual' }))
  await waitFor(() => expect(bodies).toHaveLength(2))
  expect(bodies[1]).toMatchObject({ version: 1, inputs: { days: {}, toggles: { finland_residual: false } } })
})

test('the model card names the site of every target and calls the baseline relative survival', async () => {
  serve()
  renderAt('/projects/p1/models/m1')
  await screen.findByRole('heading', { name: 'Standard times, calendar days' })
  const lung = document.querySelector('tr[data-site="lung"]') as HTMLElement
  expect(within(lung).getByRole('cell', { name: 'lung' })).toBeInTheDocument()
  const colorectal = document.querySelector('tr[data-site="colorectal"]') as HTMLElement
  expect(within(colorectal).getByRole('cell', { name: 'colorectal' })).toBeInTheDocument()
  expect(screen.getByRole('cell', { name: '38 per 100' })).toBeInTheDocument()
  expect(screen.getByRole('cell', { name: '5-year relative survival' })).toBeInTheDocument()
  expect(screen.getByText(/same age and sex without cancer/)).toBeInTheDocument()
  expect(document.body).not.toHaveTextContent(/alive/i)
})

test('the population view labels each site, and scales the bars against 100', async () => {
  serve()
  renderAt('/projects/p1/models/m1?view=population')
  const section = await screen.findByRole('heading', { name: 'lung cancer, female: 5-year relative survival per 100' })
  const figures = section.closest('section') as HTMLElement
  const bars = figures.querySelectorAll<HTMLElement>('[style]')
  expect([...bars].map((bar) => bar.style.width)).toEqual(['38%', '36%', '31%'])
  expect(screen.getByRole('table', { name: 'lung cancer' })).toBeInTheDocument()
  expect(screen.getByRole('table', { name: 'colorectal cancer' })).toBeInTheDocument()
  expect(document.body).not.toHaveTextContent(/alive/i)
})

test('the population view says when there are no figures', async () => {
  serve({ 'GET /api/models/m1/population': [] })
  renderAt('/projects/p1/models/m1?view=population')
  expect(await screen.findByText('No population figures for this model.')).toBeInTheDocument()
})

test('the population view shows an error when its figures cannot be loaded', async () => {
  serve({ 'GET /api/models/m1/population': failure })
  renderAt('/projects/p1/models/m1?view=population')
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the population figures: The model store is down.')
})
