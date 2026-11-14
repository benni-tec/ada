import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import type { DataSource, Operator, Report, ReportSource, ReportVersion, Verdict, Widget } from '@/lib/api'

import { claude, emit, json, project, renderAt, run, serveApi, session, web, widget } from './app'

// Reports, frozen at a version's run; the pipeline dialog of a widget card; the widget page.

// The chart's pipeline is a diamond: the screening source is read by a join and by an input
// slot, and the chart's operator reads both.
const chart = widget({ id: 'w1', type: 'line-chart', title: 'Coverage by region', operator_id: 'op_t' })
const value = widget({ id: 'w2', type: 'value', title: 'Latest coverage', operator_id: 'op_t' })

function operator(overrides: Partial<Operator>): Operator {
  return {
    project_id: 'p1',
    params: {},
    inputs: [],
    output: { kind: 'table', columns: [], roles: { measures: [] }, derived: false },
    materializing: false,
    created_by: claude,
    created_at: '2026-11-01T09:07:00Z',
    ...overrides,
  } as Operator
}

const lineage: Operator[] = [
  operator({ id: 'op_s', kind: 'source', params: { data_source_id: 'ds1' }, materializing: true }),
  operator({ id: 'op_r', kind: 'source', params: { data_source_id: 'ds2' }, materializing: true }),
  operator({
    id: 'op_j',
    kind: 'transform',
    params: { sql: '-- Screening by county code\nSELECT r.code, d.value FROM input_0 AS d JOIN input_1 AS r ON r.id = d.region' },
    inputs: ['op_s', 'op_r'],
  }),
  operator({ id: 'op_i', kind: 'input', params: { name: 'screening' }, inputs: ['op_s'] }),
  operator({
    id: 'op_t',
    kind: 'transform',
    params: { sql: 'SELECT * FROM input_0' },
    inputs: ['op_j', 'op_i'],
    created_by: web,
    output: {
      kind: 'table',
      columns: [
        { name: 'county_code', type: 'text', nullable: true },
        { name: 'period_start', type: 'date', nullable: true },
        { name: 'value', type: 'number', nullable: true },
        { name: 'low', type: 'number', nullable: true },
      ],
      roles: {
        time: { start: 'period_start', end: 'period_start', grain: 'year' },
        geo: { code: 'county_code', system: 'statfin', level: 'wellbeing_services_county' },
        measures: [{ value: 'value', lower: 'low' }],
      },
      derived: true,
    },
  }),
]

const projectSources = [
  { id: 'ds1', name: 'Sotkanet screening (now)', address: 'https://sotkanet.test/now' },
  { id: 'ds2', name: 'Sotkanet regions', address: 'https://sotkanet.test/regions' },
] as DataSource[]

const recorded: ReportSource[] = [
  {
    data_source_id: 'ds1',
    name: 'Sotkanet screening',
    address: 'https://sotkanet.test/3621.csv',
    access_kind: 'url',
    format: 'csv',
    operator_id: 'op_s',
    snapshot_id: 'snap1',
    fetched_at: '2026-10-30T07:00:00Z',
    content_hash: 'abcdef0123456789',
    widget_ids: ['w1', 'w2'],
  },
]

const report: Report = {
  id: 'rep1',
  project_id: 'p1',
  name: 'Screening findings',
  session_id: 's1',
  dashboard_id: null,
  latest_version_id: 'v2',
  created_at: '2026-11-02T09:00:00Z',
  revision: 2,
}

function version(overrides: Partial<ReportVersion> = {}): ReportVersion {
  return {
    id: 'v2',
    report_id: 'rep1',
    version: '1.1.0',
    run_id: 'r2',
    time_range: { start: '2024-01-01', end: '2024-12-31' },
    content: {
      blocks: [
        { type: 'heading', text: 'Screening gap', level: 1 },
        { type: 'text', text: 'Coverage fell.\n\nMostly in the north.' },
        { type: 'callout', tone: 'finding', title: 'Below target', text: 'Three counties are under 80 %.' },
        { type: 'section', title: 'Trend', blocks: [{ type: 'widget', widget_id: 'w1', caption: 'By wellbeing services county' }] },
        { type: 'widget', widget_id: 'w2', caption: '' },
      ],
      sources: recorded,
    },
    template_id: null,
    dashboard_version_id: null,
    created_by: claude,
    created_at: '2026-11-03T09:00:00Z',
    ...overrides,
  }
}

const older = version({ id: 'v1', version: '1.0.0', run_id: 'r1', time_range: { start: null, end: null } })

const rows = (operatorId: string, count: number, truncated: boolean) => ({
  columns: [
    { name: 'region', type: 'text', nullable: true },
    { name: 'geometry', type: 'json', nullable: true },
  ],
  rows: Array.from({ length: count }, (_, index) => [`${operatorId}-${index}`, index === 0 ? 'x'.repeat(200) : null]),
  truncated,
})

/** The rows requests made, as "run operator limit". */
const reads: string[] = []

function rowsOf(runId: string, operatorId: string, count: number, truncated = false) {
  return (_: unknown, request: Request) => {
    reads.push(`${runId} ${operatorId} ${new URL(request.url).searchParams.get('limit')}`)
    return rows(operatorId, count, truncated)
  }
}

function serveReport(overrides: Record<string, unknown> = {}) {
  reads.length = 0
  return serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/reports/rep1': report,
    'GET /api/reports/rep1/versions': [older, version()],
    'GET /api/report-versions/v2/sources': recorded,
    'GET /api/report-versions/v1/sources': recorded,
    'GET /api/sessions/s1': session(),
    'GET /api/widgets/w1': chart,
    'GET /api/widgets/w2': value,
    'GET /api/operators/op_t/lineage': lineage,
    'GET /api/projects/p1/sources': projectSources,
    'GET /api/runs/r2': run('r2', { snapshots: { op_s: 'snap1' } }),
    'GET /api/snapshots/snap1': {
      id: 'snap1',
      project_id: 'p1',
      operator_id: 'op_s',
      parameters_key: 'range:abc',
      content_hash: 'sha256:0123456789abcdef',
      location: 'x',
      row_count: 1234,
      fetched_at: '2026-10-30T07:00:00Z',
    },
    'GET /api/runs/r2/operators/op_t/rows': rowsOf('r2', 'op_t', 21),
    'GET /api/runs/r2/operators/op_s/rows': rowsOf('r2', 'op_s', 50, true),
    ...overrides,
  })
}

async function openPipeline(name = 'Coverage by region') {
  const card = await screen.findByRole('article', { name })
  const opener = await within(card).findByRole('button', { name: 'Pipeline' })
  act(() => opener.focus())
  fireEvent.click(opener)
  const dialog = await screen.findByRole('dialog', { name: `Pipeline of “${name}”` })
  await within(dialog).findByRole('group', { name: 'Operators, from the sources to the widget' })
  return { opener, dialog }
}

const node = (dialog: HTMLElement, name: RegExp) => within(dialog).getByRole('button', { name })

test('a report opens at its latest version, frozen, every widget at the version’s run; an older one points to the latest', async () => {
  serveReport()
  const { router } = renderAt('/projects/p1/reports/rep1')

  // The latest version is named in the address, so a new one does not swap the numbers.
  await waitFor(() => expect(router.state.location.search).toEqual({ version: '1.1.0' }))
  expect(await screen.findByRole('heading', { level: 1, name: 'Screening findings' })).toBeInTheDocument()
  expect(document.querySelector('[data-page-type="report"]')).toHaveTextContent('Report')
  expect(await screen.findByText(/Frozen at version 1\.1\.0: these numbers never change\./)).toBeInTheDocument()
  expect(screen.queryByLabelText(/Live updates/)).not.toBeInTheDocument()
  expect(screen.getByLabelText('Version')).toHaveValue('1.1.0')

  // The tree: static blocks as words, widgets in frames at the version's run.
  expect(screen.getByRole('heading', { level: 2, name: 'Screening gap' })).toBeInTheDocument()
  expect(screen.getByText('Mostly in the north.')).toBeInTheDocument()
  expect(screen.getByRole('complementary', { name: 'Below target' })).toHaveTextContent('Finding')
  expect(within(screen.getByRole('region', { name: 'Trend' })).getByText('By wellbeing services county')).toBeInTheDocument()
  expect(await screen.findByTitle('Widget: Coverage by region')).toHaveAttribute('src', 'http://localhost:5174/line-chart.html#widget=w1&run=r2&fit=content')
  expect(await screen.findByTitle('Widget: Latest coverage')).toHaveAttribute('src', 'http://localhost:5174/value.html#widget=w2&run=r2&fit=content')
  // Full size, it opens over the report at the report's run.
  const card = screen.getByRole('article', { name: 'Coverage by region' })
  await waitFor(() => expect(within(card).getByRole('link', { name: 'Open full size' })).toHaveAttribute('href', '/projects/p1/reports/rep1?version=1.1.0&open=w1'))

  // What pins the numbers, and where they come from.
  const facts = screen.getByRole('complementary', { name: 'About this version' })
  expect(facts).toHaveTextContent('Data period2024-01-01 – 2024-12-31')
  expect(facts).toHaveTextContent('Runr2')
  const source = await within(facts).findByRole('listitem')
  expect(within(source).getByRole('link', { name: 'https://sotkanet.test/3621.csv' })).toBeInTheDocument()
  expect(within(source).getByRole('time')).toHaveAttribute('dateTime', '2026-10-30T07:00:00Z')
  expect(source).toHaveTextContent('content abcdef012345')
  await waitFor(() => expect(source).toHaveTextContent('Used by “Coverage by region”, “Latest coverage”'))
  expect(screen.getByRole('link', { name: 'Why did coverage drop?' })).toHaveAttribute('href', '/projects/p1/sessions/s1')

  // An older version: its own run, and a way to the latest.
  fireEvent.change(screen.getByLabelText('Version'), { target: { value: '1.0.0' } })
  await waitFor(() => expect(router.state.location.search).toEqual({ version: '1.0.0' }))
  expect(await screen.findByText(/You are reading version 1.0.0/)).toBeInTheDocument()
  await waitFor(() => expect(screen.getByTitle('Widget: Coverage by region')).toHaveAttribute('src', 'http://localhost:5174/line-chart.html#widget=w1&run=r1&fit=content'))
  expect(screen.getByRole('complementary', { name: 'About this version' })).toHaveTextContent('Data periodAll periods')
  expect(screen.getByRole('link', { name: '1.1.0' })).toHaveAttribute('href', '/projects/p1/reports/rep1?version=1.1.0')
})

test('a text widget’s value opens the pipeline of the input it comes from', async () => {
  serveReport({
    'GET /api/widgets/w1': { ...chart, type: 'text', inputs: { gap: 'op_j' } },
    'GET /api/operators/op_j/lineage': lineage.slice(0, 3),
  })
  renderAt('/projects/p1/reports/rep1?version=1.1.0')

  const frame = (await screen.findByTitle('Widget: Coverage by region')) as HTMLIFrameElement
  expect(frame.getAttribute('src')).toBe('http://localhost:5174/text.html#widget=w1&run=r2&fit=content')
  act(() =>
    window.dispatchEvent(new MessageEvent('message', { data: { type: 'ada:open-pipeline', input: 'gap' }, source: frame.contentWindow })),
  )
  const dialog = await screen.findByRole('dialog', { name: 'Pipeline of “Coverage by region”, input “gap”' })
  const graph = await within(dialog).findByRole('group', { name: 'Operators, from the sources to the widget' })
  expect(within(graph).getAllByRole('button').map((button) => button.dataset.operator)).toEqual(['op_s', 'op_r', 'op_j'])
  expect(node(dialog, /the widget reads this/)).toHaveAttribute('data-operator', 'op_j')
  expect(node(dialog, /the widget reads this/)).toHaveAttribute('aria-pressed', 'true')
})

test('a text widget in a report shows its review; “Review again” reviews it at the version’s run, and a new verdict arrives live', async () => {
  const reviewed: string[] = []
  const verdict: Verdict = {
    kind: 'text_widget',
    outcome: 'fail',
    passed: false,
    blocking: false,
    findings: [{ message: 'No input backs 13.2', excerpt: 'a gap of 13.2', severity: 'error' }],
    model: 'gemini/pro',
    reason: null,
    content_hash: 'sha256:1',
    checked_at: '2026-11-14T10:00:00Z',
  }
  let text: Widget = { ...chart, type: 'text', verdict: null }
  serveReport({
    'GET /api/widgets/w1': () => text,
    'POST /api/widgets/w1/review': (_: unknown, request: Request) => {
      reviewed.push(new URL(request.url).search)
      text = { ...text, verdict }
      return text
    },
  })
  renderAt('/projects/p1/reports/rep1?version=1.1.0')

  const card = await screen.findByRole('article', { name: 'Coverage by region' })
  // Only text and custom widgets are judged.
  expect(within(await screen.findByRole('article', { name: 'Latest coverage' })).queryByRole('button', { name: /review/i })).toBeNull()
  fireEvent.click(await within(card).findByRole('button', { name: /Not reviewed/ }))
  const popover = await screen.findByRole('dialog')
  expect(popover).toHaveTextContent('Not reviewed yet')
  fireEvent.click(within(popover).getByRole('button', { name: 'Review again' }))
  expect(await within(popover).findByRole('list', { name: 'Findings' })).toHaveTextContent('No input backs 13.2')
  expect(reviewed).toEqual(['?run_id=r2'])
  expect(within(card).getByRole('button', { name: /Failed: 1 finding/ })).toBeInTheDocument()

  // The worker stores a new verdict; the update brings it.
  text = { ...text, verdict: { ...verdict, outcome: 'pass', passed: true, findings: [] } }
  act(() => emit('widget.updated', { widget_id: 'w1' }))
  expect(await within(card).findByRole('button', { name: /Reviewed ✓/ })).toBeInTheDocument()
})

test('the pipeline is read when its dialog opens: the graph, the details and a preview at the version’s run; a source shows its snapshot', async () => {
  const fetch = serveReport()
  renderAt('/projects/p1/reports/rep1?version=1.1.0')

  const card = await screen.findByRole('article', { name: 'Coverage by region' })
  expect(within(card).getByRole('button', { name: 'Pipeline' })).toHaveAttribute('aria-haspopup', 'dialog')
  const asked = () => fetch.mock.calls.map(([input]) => new URL(input instanceof Request ? input.url : String(input)).pathname)
  expect(asked().filter((path) => path.includes('/rows') || path.includes('/lineage') || path.startsWith('/api/runs/'))).toEqual([])

  const { dialog } = await openPipeline()
  expect(dialog).toHaveAttribute('aria-modal', 'true')
  expect(dialog).toHaveAccessibleDescription(/^Frozen: report version 1\.1\.0, run r2\./)

  // Column by column: the two sources, then the slot and the join (ordered by where their
  // inputs sit), then the widget's. The shared source is drawn once; five edges.
  const graph = within(dialog).getByRole('group', { name: 'Operators, from the sources to the widget' })
  expect(within(graph).getAllByRole('button').map((button) => button.dataset.operator)).toEqual(['op_s', 'op_r', 'op_i', 'op_j', 'op_t'])
  expect(dialog.querySelectorAll('[data-testid="pipeline-edges"] path[data-from]')).toHaveLength(5)
  // Names: the source as the version recorded it, the query's leading comment, the slot.
  expect(node(dialog, /^Source: Sotkanet screening, stores a snapshot$/)).toBeInTheDocument()
  expect(node(dialog, /^SQL: Screening by county code$/)).toBeInTheDocument()
  expect(node(dialog, /^Input: Slot “screening”$/)).toBeInTheDocument()

  // The widget's operator is selected, with its details and the first 50 rows of the run.
  const target = node(dialog, /the widget reads this/)
  expect(target).toHaveAttribute('aria-pressed', 'true')
  expect(target).toHaveFocus()
  const details = within(dialog).getByRole('complementary', { name: 'Details' })
  expect(details).toHaveTextContent('SELECT * FROM input_0')
  expect(details).toHaveTextContent('Geography: statfin, wellbeing services county')
  expect(details).toHaveTextContent('Lower bound of value')
  expect(within(details).getByText('Person (web)')).toBeInTheDocument()
  const preview = await within(dialog).findByRole('region', { name: 'Rows' })
  expect(await within(preview).findByText('op_t-20')).toBeInTheDocument()
  expect(within(dialog).getByRole('table', { name: '21 rows' })).toBeInTheDocument()

  // A source: where its data came from, as the version recorded it, and the run's snapshot.
  fireEvent.click(node(dialog, /^Source: Sotkanet screening/))
  expect(target).toHaveAttribute('aria-pressed', 'false')
  const source = within(dialog).getByRole('complementary', { name: 'Details' })
  expect(source).toHaveTextContent('https://sotkanet.test/3621.csv')
  expect(source).toHaveTextContent('A snapshot of its output (materializing)')
  const snapshot = await within(source).findByRole('region', { name: 'Snapshot in this run' })
  expect(await within(snapshot).findByText('sha256:0123456789abcdef')).toBeInTheDocument()
  expect(snapshot).toHaveTextContent('1,234')
  expect(await within(dialog).findByRole('table', { name: 'First 50 of 1,234 rows' })).toBeInTheDocument()
  // Long values are cut short, whole in the title.
  expect(within(dialog).getByTitle('x'.repeat(200)).textContent).toHaveLength(61)
  expect(reads).toEqual(['r2 op_t 50', 'r2 op_s 50'])
})

test('in the pipeline dialog the arrow keys walk the graph; the focus stays inside, and Escape gives it back', async () => {
  serveReport()
  renderAt('/projects/p1/reports/rep1?version=1.1.0')
  const { dialog, opener } = await openPipeline()
  // The page behind is out of reach.
  expect(opener.closest('[inert]')).not.toBeNull()

  fireEvent.keyDown(node(dialog, /the widget reads this/), { key: 'ArrowLeft' })
  const join = node(dialog, /^SQL: Screening by county code$/)
  expect(join).toHaveFocus()
  expect(join).toHaveAttribute('aria-pressed', 'true')
  expect(within(dialog).getByRole('complementary', { name: 'Details' })).toHaveTextContent('JOIN input_1 AS r')
  fireEvent.keyDown(join, { key: 'ArrowUp' })
  const slot = node(dialog, /^Input: Slot “screening”$/)
  expect(slot).toHaveFocus()
  fireEvent.keyDown(slot, { key: 'ArrowLeft' })
  expect(node(dialog, /^Source: Sotkanet screening/)).toHaveFocus()
  fireEvent.keyDown(node(dialog, /^Source: Sotkanet screening/), { key: 'ArrowRight' })
  expect(slot).toHaveFocus()
  // Nowhere to go: the focus stays.
  fireEvent.keyDown(slot, { key: 'ArrowUp' })
  expect(slot).toHaveFocus()

  const close = within(dialog).getByRole('button', { name: 'Close' })
  const last = [...dialog.querySelectorAll<HTMLElement>('button, [tabindex="0"]')].at(-1)!
  act(() => last.focus())
  fireEvent.keyDown(last, { key: 'Tab' })
  expect(close).toHaveFocus()
  fireEvent.keyDown(close, { key: 'Tab', shiftKey: true })
  expect(last).toHaveFocus()

  fireEvent.keyDown(dialog, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  await waitFor(() => expect(opener).toHaveFocus())
  expect(opener.closest('[inert]')).toBeNull()
})

test('a report is generated from a dashboard and opened', async () => {
  const sent: unknown[] = []
  serveReport({
    'GET /api/projects/p1/dashboards': [
      { id: 'd1', project_id: 'p1', name: 'Coverage' },
      { id: 'd2', project_id: 'p1', name: 'Mortality' },
    ],
    'POST /api/dashboards/d2/reports': (body: unknown) => {
      sent.push(body)
      return sent.length === 1 ? json({ detail: 'Dashboard d2 shows no widgets' }, 422) : json(version({ version: '1.0.0' }), 201)
    },
  })
  const { router } = renderAt('/projects/p1/reports/new?dashboard=d2')

  expect(await screen.findByLabelText('Dashboard')).toHaveValue('d2')
  fireEvent.change(screen.getByLabelText('Report name'), { target: { value: '  Mortality, monthly ' } })
  fireEvent.click(screen.getByRole('button', { name: 'Generate report' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Not generated: Dashboard d2 shows no widgets')

  fireEvent.click(screen.getByRole('button', { name: 'Generate report' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/projects/p1/reports/rep1'))
  expect(router.state.location.search).toEqual({ version: '1.0.0' })
  expect(sent).toEqual([{ name: 'Mortality, monthly' }, { name: 'Mortality, monthly' }])
})

test('the widget page previews the run named in its address, or one run of its own', async () => {
  let started = 0
  serveReport({
    'POST /api/projects/p1/runs': () => json(run(`r${++started + 4}`), 201),
    'GET /api/runs/r5': run('r5'),
    'GET /api/runs/r5/operators/op_t/rows': rowsOf('r5', 'op_t', 1),
  })
  const { router } = renderAt('/projects/p1/widgets/w1?run=r2')

  let { dialog } = await openPipeline()
  expect(dialog).toHaveAccessibleDescription(/^Frozen: the run named in this page’s address, run r2\./)
  await within(dialog).findByText('op_t-0')
  expect(started).toBe(0)
  fireEvent.keyDown(dialog, { key: 'Escape' })

  await act(() => router.navigate({ to: '/projects/$projectId/widgets/$widgetId', params: { projectId: 'p1', widgetId: 'w1' } }))
  expect(await screen.findByTitle('Widget: Coverage by region')).toHaveAttribute('src', 'http://localhost:5174/line-chart.html#widget=w1&run=r5')
  ;({ dialog } = await openPipeline())
  expect(dialog).toHaveAccessibleDescription('This page’s current run, follows new data (run r5).')
  await within(dialog).findByText('op_t-0')
  expect(reads).toEqual(['r2 op_t 50', 'r5 op_t 50'])
  expect(started).toBe(1)
})
