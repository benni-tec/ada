import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import type { Case, CaseResult, CaseState, CaseType, CaseWithResult, Evaluation, ModelOnCase, ModelVersion, SavedCase, StatisticalModel } from '@/lib/api'

import { project, renderAt, serveApi, web } from './app'

// The case pages: the form a case type's schema generates, the case page with its data
// card, its models and the result sheet, and a model's page with every eligible case.

const caseType: CaseType = {
  id: 'ct1',
  project_id: 'p1',
  name: 'Suspected cancer pathway',
  description: 'A patient on a suspected cancer pathway, step by step. Synthetic only.',
  fields: [
    { name: 'site', type: 'enum', levels: ['lung', 'colorectal'], required: true, label: 'Site', help: '' },
    { name: 'presentation', type: 'enum_list', levels: ['lung_symptoms_smoker', 'lung_imaging'], required: false, label: 'Presentation', help: 'The pathway criteria the presentation meets' },
    { name: 'days', type: 'day_map', levels: ['symptoms_to_contact', 'contact_to_physician', 'physician_to_imaging'], required: false, label: 'Days per step', help: '' },
    { name: 'treatment_started', type: 'boolean', levels: [], required: false, label: 'Treatment started', help: '' },
    { name: 'age', type: 'integer', levels: [], required: false, label: 'Age', help: '' },
    { name: 'referral_date', type: 'date', levels: [], required: false, label: 'Referral date', help: '' },
    { name: 'county', type: 'text', levels: [], required: false, label: 'Wellbeing services county', help: '' },
  ],
  revision: 1,
  created_by: web,
  created_at: '2026-11-14T10:00:00Z',
}

const pathwayModel: StatisticalModel = {
  id: 'm1',
  project_id: 'p1',
  name: 'Patient pathway model',
  description: 'Fast-track trigger, deadlines, survival second.',
  kind: 'patient_pathway',
  latest_version: 1,
  case_type_id: 'ct1',
  auto_run: true,
  created_by: web,
  created_at: '2026-11-14T10:00:00Z',
}

const trialModel: StatisticalModel = {
  ...pathwayModel,
  id: 'm2',
  name: 'Clinical trial matcher',
  description: 'Recruiting trials by site, age and sex.',
  kind: 'trial_matcher',
  auto_run: false,
}

const evaluation = {
  model_id: 'm1',
  version: 1,
  trigger: {
    suspicion: { stage: 'suspicion', fired: true, countries: ['Sweden'], criteria: [] },
    well_founded: { stage: 'well_founded', fired: true, countries: ['Norway', 'Sweden'], criteria: [] },
    clock_start: 27,
    note: 'This presentation would start a pathway in Norway and Sweden.',
  },
  deadlines: [{ label: 'Treatment start', rule: '43 days after the trigger', countries: ['Norway', 'Sweden'], due_day: 70, status: 'overdue', by: 3 }],
  pathway: [{ step: 'contact_to_physician', label: 'First contact → physician', days: 14, target: 7, gap: 7, countries: [], patient_interval: false, current: false }],
  days_behind: 20,
  survival: { now: 35, on_target: 35, by_setting: {}, range_now: { low: 32, high: 39 }, range_on_target: { low: 32, high: 39 }, setting: {} },
  levers: [],
  flags: ['Offer a patient navigator to keep the next steps on time.'],
  warnings: [],
  contributions: [],
} as unknown as Evaluation

const theCase: Case = {
  id: 'c1',
  case_type_id: 'ct1',
  key: 'SYN-0042',
  values: { site: 'lung', days: { symptoms_to_contact: 51, contact_to_physician: 14, physician_to_imaging: 13 }, county: 'Pirkanmaa' },
  schema_revision: 1,
  revision: 1,
  created_at: '2026-11-15T10:42:00Z',
  updated_at: '2026-11-15T10:42:00Z',
}

const pathwayReads = ['site', 'sex', 'age_band', 'education', 'route', 'stage', 'intent', 'modality', 'presentation', 'days', 'treatment_started']

function result(overrides: Partial<CaseResult> = {}): CaseResult {
  return {
    id: 'r1',
    case_id: 'c1',
    model_id: 'm1',
    version: 1,
    case_revision: 1,
    section: {
      kind: 'patient_pathway',
      title: 'Patient pathway model',
      summary: 'Treatment start overdue by 3 days',
      status: 'urgent',
      columns: { trigger: 'well_founded', treatment_start_status: 'overdue', treatment_start_by: 3 },
      attention: { open: true, overdue_by: 3, due_in: null },
      reads: {},
      body: evaluation as unknown as Record<string, unknown>,
    },
    trigger: 'auto',
    created_by: web,
    created_at: '2026-11-15T10:42:00Z',
    ...overrides,
  }
}

const trialResult = result({
  id: 'r2',
  model_id: 'm2',
  trigger: 'request',
  created_at: '2026-11-15T11:00:00Z',
  section: { kind: 'trial_matcher', title: 'Clinical trial matcher', summary: '2 recruiting trials', status: 'ok', columns: { trials: 2 }, attention: { open: false }, body: {}, reads: {} },
})

/** The fake API around one case; `state` changes as the case is saved and evaluated. */
function serve() {
  const state: CaseState = { case: theCase, events: [], results: [result()] }
  const models = (): ModelOnCase[] =>
    [pathwayModel, trialModel].map((m) => {
      const mine = state.results.filter((r) => r.model_id === m.id)
      return { model_id: m.id, name: m.name, kind: m.kind, version: 1, auto_run: m.auto_run, reads: m.kind === 'patient_pathway' ? pathwayReads : ['site'], latest: mine[0] ?? null, results: mine.length }
    })
  const puts: unknown[] = []
  const fetch = serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/projects/p1/models': [pathwayModel, trialModel],
    'GET /api/projects/p1/case-types': [caseType],
    'GET /api/case-types/ct1': caseType,
    'GET /api/case-types/ct1/cases': () => [{ case: state.case, latest: state.results.slice(0, 1) }],
    'GET /api/case-types/ct1/open-cases': () => [{ case: state.case, latest: state.results[0] }],
    'GET /api/case-types/ct1/cases/SYN-0042': () => state,
    'GET /api/case-types/ct1/cases/SYN-0042/models': models,
    'PUT /api/case-types/ct1/cases/SYN-0042': (body: unknown) => {
      puts.push(body)
      const { values } = body as { values: Case['values'] }
      const revision = state.case.revision + 1
      state.case = { ...state.case, values, revision }
      state.results = [result({ id: `r-save-${puts.length}`, case_revision: revision }), ...state.results]
      const saved: SavedCase = { ...state, ran: ['m1'] }
      return saved
    },
    'POST /api/case-types/ct1/cases/SYN-0042/evaluate': (body: unknown) => {
      expect(body).toEqual({ model_id: 'm2' })
      state.results = [trialResult, ...state.results]
      return trialResult
    },
  })
  return { fetch, state, puts }
}

test('the sidebar groups Cases and Models under Pathways', async () => {
  serve()
  renderAt('/projects/p1/cases')
  const nav = await screen.findByRole('navigation', { name: 'Project' })
  const pathways = within(nav).getByRole('group', { name: 'Pathways' })
  expect(within(pathways).getByRole('link', { name: 'Cases' })).toHaveAttribute('href', '/projects/p1/cases')
  expect(within(pathways).getByRole('link', { name: 'Models' })).toHaveAttribute('href', '/projects/p1/models')
  // One case type: shown directly, with its cases and the latest result.
  expect(await screen.findByRole('heading', { name: 'Suspected cancer pathway', level: 1 })).toBeInTheDocument()
  expect(await screen.findByRole('link', { name: 'SYN-0042' })).toHaveAttribute('href', '/projects/p1/cases/ct1/SYN-0042')
  expect(await screen.findByText('Treatment start overdue by 3 days')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'New case' })).toHaveAttribute('href', '/projects/p1/cases/new?type=ct1')
})

test('the new-case form shows a control for every field of the schema', async () => {
  serve()
  renderAt('/projects/p1/cases/new?type=ct1')
  expect(await screen.findByLabelText('Key')).toBeInTheDocument()
  const site = screen.getByLabelText(/^Site/)
  expect(site.tagName).toBe('SELECT')
  expect(within(site).getAllByRole('option').map((o) => o.textContent)).toEqual(['Choose…', 'Lung', 'Colorectal'])
  const presentation = screen.getByRole('group', { name: 'Presentation' })
  expect(within(presentation).getAllByRole('checkbox')).toHaveLength(2)
  expect(presentation).toHaveAccessibleDescription('The pathway criteria the presentation meets')
  const days = screen.getByRole('group', { name: 'Days per step' })
  expect(within(days).getAllByRole('spinbutton')).toHaveLength(3)
  expect(within(days).getByLabelText('First contact → physician')).toBeInTheDocument()
  expect(screen.getByLabelText('Treatment started')).toHaveAttribute('type', 'checkbox')
  expect(screen.getByLabelText('Age')).toHaveAttribute('type', 'number')
  expect(screen.getByLabelText('Referral date')).toHaveAttribute('type', 'date')
  expect(screen.getByLabelText('Wellbeing services county')).toHaveAttribute('type', 'text')
})

test('saving a new case opens the case page and names the models that ran', async () => {
  const { puts } = serve()
  const { router } = renderAt('/projects/p1/cases/new?type=ct1')
  fireEvent.change(await screen.findByLabelText('Key'), { target: { value: 'SYN-0042' } })
  fireEvent.change(screen.getByLabelText(/^Site/), { target: { value: 'lung' } })
  fireEvent.change(within(screen.getByRole('group', { name: 'Days per step' })).getByLabelText('First contact → physician'), { target: { value: '14' } })
  fireEvent.change(screen.getByLabelText('Wellbeing services county'), { target: { value: 'Pirkanmaa' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save case' }))

  expect(await screen.findByRole('heading', { name: 'SYN-0042', level: 1 })).toBeInTheDocument()
  expect(router.state.location.pathname).toBe('/projects/p1/cases/ct1/SYN-0042')
  expect(puts[0]).toEqual({ values: { site: 'lung', days: { contact_to_physician: 14 }, county: 'Pirkanmaa' } })
  expect(screen.getByText('Case SYN-0042 saved. Patient pathway model ran automatically.')).toBeInTheDocument()
})

test('the case page marks the case type’s own fields and edits in place', async () => {
  const { puts } = serve()
  renderAt('/projects/p1/cases/ct1/SYN-0042')
  const card = await screen.findByRole('region', { name: 'Case data' })
  // County is read by no model; site is read by the pathway model.
  await waitFor(() => expect(within(card).getByText('Wellbeing services county').closest('[data-own]')).not.toBeNull())
  expect(within(card).getByText('Site').closest('[data-own]')).toBeNull()
  const steps = within(card).getByRole('list', { name: 'Steps' })
  expect(within(steps).getByText(/51 days of symptoms before/)).toBeInTheDocument()
  expect(within(steps).getByText('Today · no imaging done yet')).toBeInTheDocument()

  fireEvent.click(within(card).getByRole('button', { name: 'Edit the case data' }))
  fireEvent.change(within(card).getByLabelText('Wellbeing services county'), { target: { value: 'Lappi' } })
  fireEvent.click(within(card).getByRole('button', { name: 'Save' }))

  expect(await screen.findByText('Saved as revision 2. Patient pathway model ran automatically.')).toBeInTheDocument()
  expect(puts[0]).toEqual({ values: { ...theCase.values, county: 'Lappi' } })
  // A new revision: the card is shown again, with the saved values.
  const saved = screen.getByRole('region', { name: 'Case data' })
  expect(await within(saved).findByText('Lappi')).toBeInTheDocument()
  expect(within(saved).queryByRole('button', { name: 'Save' })).not.toBeInTheDocument()
  expect(screen.getByText(/^Revision 2 · saved/)).toBeInTheDocument()
})

test('a model without a result offers Evaluate, which opens the stored result in the sheet', async () => {
  serve()
  renderAt('/projects/p1/cases/ct1/SYN-0042')
  const models = await screen.findByRole('region', { name: 'Models' })
  const trialRow = (await within(models).findByRole('link', { name: 'Clinical trial matcher' })).closest('tr') as HTMLElement
  expect(within(trialRow).getByText('Not evaluated for this case')).toBeInTheDocument()
  fireEvent.click(within(trialRow).getByRole('button', { name: 'Evaluate' }))

  const sheet = await screen.findByRole('dialog', { name: 'Clinical trial matcher' })
  expect(within(sheet).getByText('2 recruiting trials')).toBeInTheDocument()
  expect(within(sheet).getByText('Evaluated on request')).toBeInTheDocument()
  expect(within(sheet).getByRole('combobox', { name: 'Earlier results' })).toHaveDisplayValue(/rev\. 1 \(only result\)/)
  expect(within(sheet).getByRole('button', { name: 'Evaluate again' })).toBeInTheDocument()
  // The row now offers the stored result.
  await waitFor(() => expect(within(trialRow).getByRole('button', { name: 'View result', hidden: true })).toBeInTheDocument())
})

test('the pathway result in the sheet leads with the deadlines', async () => {
  serve()
  renderAt('/projects/p1/cases/ct1/SYN-0042')
  const models = await screen.findByRole('region', { name: 'Models' })
  const row = (await within(models).findByRole('link', { name: 'Patient pathway model' })).closest('tr') as HTMLElement
  fireEvent.click(within(row).getByRole('button', { name: 'View result' }))
  const sheet = await screen.findByRole('dialog', { name: 'Patient pathway model' })
  expect(within(sheet).getByText('Ran automatically')).toBeInTheDocument()
  expect(within(sheet).getByText(/would start a pathway in Norway and Sweden/)).toBeInTheDocument()
  expect(within(sheet).getByText('overdue by 3 days')).toBeInTheDocument()
  expect(within(sheet).getByText('Offer a patient navigator to keep the next steps on time.')).toBeInTheDocument()
  // Survival is relative survival per 100, said so, never "alive".
  const survival = sheet.querySelector('[data-section="survival"]') as HTMLElement
  expect(within(survival).getByRole('heading', { name: '5-year relative survival, per 100' })).toBeInTheDocument()
  expect(within(survival).getByRole('img', { name: '5-year relative survival 35 per 100' })).toBeInTheDocument()
  expect(within(survival).getByText(/same age and sex without cancer/)).toBeInTheDocument()
  expect(sheet).not.toHaveTextContent(/alive/i)
})

test('the model page lists every eligible case, with "Not run" where there is no result', async () => {
  const other: Case = { ...theCase, id: 'c2', key: 'SYN-0117', values: { site: 'colorectal', county: 'Lappi' } }
  const rows: CaseWithResult[] = [
    { case: theCase, latest: result() },
    { case: other, latest: null },
  ]
  serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/models/m1': pathwayModel,
    'GET /api/models/m1/versions/latest': { id: 'v1', model_id: 'm1', version: 1, created_by: web, created_at: '2026-11-14T10:00:00Z' } as unknown as ModelVersion,
    'GET /api/models/m1/cases': rows,
    'GET /api/case-types/ct1': caseType,
  })
  renderAt('/projects/p1/models/m1?view=cases')
  const table = await screen.findByRole('region', { name: 'Cases' })
  const first = (await within(table).findByRole('link', { name: 'SYN-0042' })).closest('tr') as HTMLElement
  const second = within(table).getByRole('link', { name: 'SYN-0117' }).closest('tr') as HTMLElement
  expect(within(first).getByText('Treatment start overdue by 3 days')).toBeInTheDocument()
  expect(within(first).getByText(/^Automatically · /)).toBeInTheDocument()
  expect(within(first).getByRole('button', { name: 'View' })).toBeInTheDocument()
  expect(within(second).getByText('Not run')).toBeInTheDocument()
  expect(within(second).getByRole('button', { name: 'Evaluate' })).toBeInTheDocument()
  expect(within(second).getByText('Lappi')).toBeInTheDocument()

  const filters = within(table).getByRole('group', { name: 'Filter cases' })
  expect(within(filters).getByRole('button', { name: 'All 2' })).toHaveAttribute('aria-pressed', 'true')
  expect(within(filters).getByRole('button', { name: 'Overdue 1' })).toBeInTheDocument()
  fireEvent.click(within(filters).getByRole('button', { name: 'Not run 1' }))
  expect(within(table).queryByRole('link', { name: 'SYN-0042' })).not.toBeInTheDocument()
  expect(within(table).getByRole('link', { name: 'SYN-0117' })).toBeInTheDocument()
  expect(screen.getByText('eligible cases').previousElementSibling).toHaveTextContent('2')
  expect(screen.getByText('with a result').previousElementSibling).toHaveTextContent('1')
})
