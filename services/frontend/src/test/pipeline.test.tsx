import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import type { DataSource, Operator, Report, ReportSource, ReportVersion } from '@/lib/api'

import { claude, json, project, renderAt, serveApi, session, web, widget } from './app'

// A widget whose pipeline is a diamond: the screening source is read by a join and by an
// input slot, and the map's operator reads both.

const map = widget({ id: 'w1', type: 'map', title: 'Screening by county', operator_id: 'op_t' })

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
  operator({
    id: 'op_s',
    kind: 'source',
    params: { data_source_id: 'ds1' },
    materializing: true,
    output: {
      kind: 'table',
      columns: [
        { name: 'region', type: 'integer', nullable: true },
        { name: 'value', type: 'number', nullable: true },
      ],
      roles: { measures: [{ value: 'value' }] },
      derived: false,
    },
  }),
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
        { name: 'period_end', type: 'date', nullable: true },
        { name: 'value', type: 'number', nullable: true },
        { name: 'low', type: 'number', nullable: true },
        { name: 'high', type: 'number', nullable: true },
      ],
      roles: {
        time: { start: 'period_start', end: 'period_end', grain: 'year' },
        geo: { code: 'county_code', system: 'statfin', level: 'wellbeing_services_county' },
        measures: [{ value: 'value', lower: 'low', upper: 'high' }],
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
    address: 'https://sotkanet.test/indicators/3621?years=2024',
    access_kind: 'url',
    format: 'json',
    operator_id: 'op_s',
    snapshot_id: 'snap1',
    fetched_at: '2026-10-30T07:00:00Z',
    content_hash: 'abcdef0123456789',
    widget_ids: ['w1'],
  },
]

const report: Report = {
  id: 'rep1',
  project_id: 'p1',
  name: 'Screening findings',
  session_id: 's1',
  dashboard_id: null,
  latest_version_id: 'v1',
  created_at: '2026-11-02T09:00:00Z',
  revision: 1,
}

const version: ReportVersion = {
  id: 'v1',
  report_id: 'rep1',
  version: '1.1.0',
  run_id: 'r2',
  time_range: { start: '2024-01-01', end: '2024-12-31' },
  content: { blocks: [{ type: 'widget', widget_id: 'w1', caption: '' }], sources: recorded },
  template_id: null,
  dashboard_version_id: null,
  created_by: claude,
  created_at: '2026-11-03T09:00:00Z',
}

function run(id: string, snapshots: Record<string, string> = {}) {
  return { id, project_id: 'p1', time_range: {}, bindings: {}, snapshots, started_by: web, started_at: '2026-11-03T08:00:00Z' }
}

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

function serveReport(overrides: Record<string, unknown> = {}) {
  reads.length = 0
  return serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/reports/rep1': report,
    'GET /api/reports/rep1/versions': [version],
    'GET /api/report-versions/v1/sources': recorded,
    'GET /api/sessions/s1': session(),
    'GET /api/widgets/w1': map,
    'GET /api/operators/op_t/lineage': lineage,
    'GET /api/projects/p1/sources': projectSources,
    'GET /api/runs/r2': run('r2', { op_s: 'snap1' }),
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
    'GET /api/runs/r2/operators/op_t/rows': (_: unknown, request: Request) => {
      reads.push(`r2 op_t ${new URL(request.url).searchParams.get('limit')}`)
      return rows('op_t', 21, false)
    },
    'GET /api/runs/r2/operators/op_s/rows': (_: unknown, request: Request) => {
      reads.push(`r2 op_s ${new URL(request.url).searchParams.get('limit')}`)
      return rows('op_s', 50, true)
    },
    ...overrides,
  })
}

async function openPipeline() {
  const card = await screen.findByRole('article', { name: 'Screening by county' })
  const opener = await within(card).findByRole('button', { name: 'Pipeline' })
  opener.focus()
  fireEvent.click(opener)
  const dialog = await screen.findByRole('dialog', { name: 'Pipeline of “Screening by county”' })
  // The pipeline is read when the dialog opens.
  await within(dialog).findByRole('group', { name: 'Operators, from the sources to the widget' })
  return { card, opener, dialog }
}

const node = (dialog: HTMLElement, name: RegExp) => within(dialog).getByRole('button', { name })

test('the footer opens the pipeline with one button, and reads it only then', async () => {
  const fetch = serveReport()
  renderAt('/projects/p1/reports/rep1?version=1.1.0')

  const card = await screen.findByRole('article', { name: 'Screening by county' })
  const footer = card.querySelector('footer')!
  const opener = within(footer).getByRole('button', { name: 'Pipeline' })
  expect(opener).toHaveAttribute('aria-haspopup', 'dialog')
  // Not on a dashboard: the action is adding it to one; and it opens full size.
  expect(within(footer).getByRole('button', { name: 'Add to dashboard' })).toBeInTheDocument()
  expect(within(footer).getByRole('link', { name: 'Open full size' })).toHaveAttribute(
    'href',
    '/projects/p1/reports/rep1?version=1.1.0&open=w1',
  )
  const lineageReads = () => fetch.mock.calls.filter(([request]) => String((request as Request).url).endsWith('/lineage'))
  expect(lineageReads()).toHaveLength(0)

  fireEvent.click(opener)
  const dialog = await screen.findByRole('dialog', { name: 'Pipeline of “Screening by county”' })
  expect(await within(dialog).findByRole('button', { name: /the widget reads this/ })).toBeInTheDocument()
  expect(lineageReads()).toHaveLength(1)
})

test('the dialog draws the graph, starts at the widget’s operator and previews it in the version’s run', async () => {
  serveReport()
  renderAt('/projects/p1/reports/rep1?version=1.1.0')
  const { dialog } = await openPipeline()

  expect(dialog).toHaveAttribute('aria-modal', 'true')
  expect(dialog).toHaveAccessibleDescription(/^Frozen: report version 1\.1\.0, run r2\./)

  const graph = within(dialog).getByRole('group', { name: 'Operators, from the sources to the widget' })
  const nodes = within(graph).getAllByRole('button')
  // Column by column: the two sources, then the slot and the join (ordered by where their
  // inputs sit), then the widget's.
  expect(nodes.map((button) => button.dataset.operator)).toEqual(['op_s', 'op_r', 'op_i', 'op_j', 'op_t'])
  expect(nodes.map((button) => button.dataset.layer)).toEqual(['0', '0', '1', '1', '2'])
  // The shared source is drawn once; five edges.
  expect(dialog.querySelectorAll('[data-testid="pipeline-edges"] path[data-from]')).toHaveLength(5)
  expect(dialog.querySelectorAll('path[data-from="op_s"]')).toHaveLength(2)

  // Names: the source, the query's leading comment, the slot. Materializing is said.
  expect(node(dialog, /^Source: Sotkanet screening, stores a snapshot$/)).toBeInTheDocument()
  expect(node(dialog, /^SQL: Screening by county code$/)).toBeInTheDocument()
  expect(node(dialog, /^Input: Slot “screening”$/)).toBeInTheDocument()
  expect(within(dialog).getByRole('list', { name: 'Legend' })).toHaveTextContent('Materializing')

  // The widget's operator is selected and has the focus.
  const target = node(dialog, /the widget reads this/)
  expect(target).toHaveAttribute('aria-pressed', 'true')
  expect(target).toHaveFocus()
  const details = within(dialog).getByRole('complementary', { name: 'Details' })
  expect(details).toHaveTextContent('SELECT * FROM input_0')
  expect(details).toHaveTextContent('Time: period start (year)')
  expect(details).toHaveTextContent('Geography: statfin, wellbeing services county')
  expect(details).toHaveTextContent('Lower bound of value')
  expect(details).toHaveTextContent('input_0SQL: Screening by county code')
  expect(within(details).getByText('Person (web)')).toBeInTheDocument()

  // The preview reads the card's run, 50 rows at most, and starts no run.
  const preview = await within(dialog).findByRole('region', { name: 'Rows' })
  expect(await within(preview).findByText('op_t-20')).toBeInTheDocument()
  expect(reads).toEqual(['r2 op_t 50'])
  expect(within(dialog).getByRole('table', { name: '21 rows' })).toBeInTheDocument()
})

test('clicking a source shows where its data came from and the snapshot the run used', async () => {
  serveReport()
  renderAt('/projects/p1/reports/rep1?version=1.1.0')
  const { dialog } = await openPipeline()

  fireEvent.click(node(dialog, /^Source: Sotkanet screening/))
  expect(node(dialog, /^Source: Sotkanet screening/)).toHaveAttribute('aria-pressed', 'true')
  expect(node(dialog, /the widget reads this/)).toHaveAttribute('aria-pressed', 'false')

  const details = within(dialog).getByRole('complementary', { name: 'Details' })
  // As the version recorded it, not as the source is now.
  expect(details).toHaveTextContent('https://sotkanet.test/indicators/3621?years=2024')
  expect(details).toHaveTextContent('A snapshot of its output (materializing)')
  const snapshot = await within(details).findByRole('region', { name: 'Snapshot in this run' })
  expect(await within(snapshot).findByText('sha256:0123456789abcdef')).toBeInTheDocument()
  expect(snapshot).toHaveTextContent('1,234')
  expect(within(snapshot).getByRole('time')).toHaveAttribute('dateTime', '2026-10-30T07:00:00Z')

  expect(await within(dialog).findByRole('table', { name: 'First 50 of 1,234 rows' })).toBeInTheDocument()
  expect(reads).toEqual(['r2 op_t 50', 'r2 op_s 50'])
  // Long values are cut short, whole in the title.
  const long = within(dialog).getByTitle('x'.repeat(200))
  expect(long.textContent).toHaveLength(61)
})

test('the arrow keys walk the graph and select as they go', async () => {
  serveReport()
  renderAt('/projects/p1/reports/rep1?version=1.1.0')
  const { dialog } = await openPipeline()
  const target = node(dialog, /the widget reads this/)

  fireEvent.keyDown(target, { key: 'ArrowLeft' })
  const join = node(dialog, /^SQL: Screening by county code$/)
  expect(join).toHaveFocus()
  expect(join).toHaveAttribute('aria-pressed', 'true')
  expect(within(dialog).getByRole('complementary', { name: 'Details' })).toHaveTextContent('JOIN input_1 AS r')

  fireEvent.keyDown(join, { key: 'ArrowUp' })
  const slot = node(dialog, /^Input: Slot “screening”$/)
  expect(slot).toHaveFocus()
  expect(within(dialog).getByRole('complementary', { name: 'Details' })).toHaveTextContent(
    '“screening”: a run may bind another pipeline to it',
  )

  fireEvent.keyDown(slot, { key: 'ArrowLeft' })
  expect(node(dialog, /^Source: Sotkanet screening/)).toHaveFocus()
  fireEvent.keyDown(node(dialog, /^Source: Sotkanet screening/), { key: 'ArrowRight' })
  expect(slot).toHaveFocus()
  // Nowhere to go: the focus stays.
  fireEvent.keyDown(slot, { key: 'ArrowUp' })
  expect(slot).toHaveFocus()
})

test('the dialog keeps the focus inside, closes on Escape and gives the focus back', async () => {
  serveReport()
  renderAt('/projects/p1/reports/rep1?version=1.1.0')
  const { dialog, opener } = await openPipeline()

  // The page behind is out of reach.
  expect(opener.closest('[inert]')).not.toBeNull()

  const close = within(dialog).getByRole('button', { name: 'Close' })
  const focusables = [...dialog.querySelectorAll<HTMLElement>('button, [tabindex="0"]')]
  const last = focusables.at(-1)!
  last.focus()
  fireEvent.keyDown(last, { key: 'Tab' })
  expect(close).toHaveFocus()
  fireEvent.keyDown(close, { key: 'Tab', shiftKey: true })
  expect(last).toHaveFocus()

  fireEvent.keyDown(dialog, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  await waitFor(() => expect(opener).toHaveFocus())
  expect(opener.closest('[inert]')).toBeNull()

  // The close button does the same.
  fireEvent.click(opener)
  fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Close' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})

// Dashboards

const dashboard = {
  id: 'd1',
  project_id: 'p1',
  name: 'Screening overview',
  current_version_id: 'v2',
  default_time_range: { start: '2022-01-01', end: '2024-12-31' },
  created_at: '2026-11-01T08:00:00Z',
  revision: 3,
}

const dashboardVersion = {
  id: 'v2',
  dashboard_id: 'd1',
  number: 2,
  slots: [{ name: 'map', description: '', widget_id: 'w1', layout: { x: 0, y: 0, w: 12, h: 4 } }],
  template_id: null,
  created_by: web,
  created_at: '2026-11-02T08:30:00Z',
}

function serveDashboard() {
  let started = 0
  reads.length = 0
  const fetch = serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/dashboards/d1': { dashboard, version: dashboardVersion },
    'GET /api/dashboards/d1/versions': [dashboardVersion],
    'GET /api/dashboards/d1/alerts': [],
    'GET /api/projects/p1/widgets': [map],
    'POST /api/dashboards/d1/runs': () => json(run(`r${++started}`), 201),
    'GET /api/operators/op_t/lineage': lineage,
    'GET /api/projects/p1/sources': projectSources,
    'GET /api/runs/r1': run('r1'),
    'GET /api/runs/r1/operators/op_t/rows': (_: unknown, request: Request) => {
      reads.push(`r1 op_t ${new URL(request.url).searchParams.get('limit')}`)
      return rows('op_t', 3, false)
    },
  })
  return { fetch, started: () => started }
}

test('on a dashboard the preview follows the dashboard’s run and opening it starts none', async () => {
  const { started } = serveDashboard()
  renderAt('/projects/p1/dashboards/d1')
  const { dialog, card } = await openPipeline()

  // The project's sources as they are now, outside a report.
  expect(within(dialog).getByRole('button', { name: /^Source: Sotkanet screening \(now\)/ })).toBeInTheDocument()
  expect(card).toBeInTheDocument()
  expect(dialog).toHaveAccessibleDescription('The dashboard’s current run, follows new data (run r1).')
  expect(await within(dialog).findByText('op_t-2')).toBeInTheDocument()
  expect(reads).toEqual(['r1 op_t 50'])
  expect(started()).toBe(1)
})

test('a dashboard card links back to its session instead of offering to pin it', async () => {
  serveDashboard()
  renderAt('/projects/p1/dashboards/d1')

  const card = await screen.findByRole('article', { name: 'Screening by county' })
  const back = within(card).getByRole('link', { name: 'Go to the session it came from' })
  expect(back).toHaveAttribute('href', '/projects/p1/sessions/s1?widget=w1')
  expect(within(card).queryByRole('button', { name: 'Add to dashboard' })).not.toBeInTheDocument()

  // The tooltip says the same as the name, on hover and on focus; Escape hides it.
  fireEvent.pointerMove(back)
  expect(await screen.findByRole('tooltip')).toHaveTextContent('Go to the session it came from')
  fireEvent.keyDown(back, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument())
  act(() => back.focus())
  expect(await screen.findByRole('tooltip')).toHaveTextContent('Go to the session it came from')
  fireEvent.keyDown(back, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument())
})

test('a widget made outside a session has the way back disabled, saying why', async () => {
  serveDashboard()
  serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/dashboards/d1': { dashboard, version: dashboardVersion },
    'GET /api/dashboards/d1/versions': [dashboardVersion],
    'GET /api/projects/p1/widgets': [{ ...map, session_id: null }],
    'POST /api/dashboards/d1/runs': json(run('r1'), 201),
    'GET /api/operators/op_t/lineage': lineage,
  })
  renderAt('/projects/p1/dashboards/d1')

  const card = await screen.findByRole('article', { name: 'Screening by county' })
  expect(within(card).queryByRole('link', { name: 'Go to the session it came from' })).not.toBeInTheDocument()
  const disabled = within(card).getByRole('button', { name: 'Not made in a session' })
  expect(disabled).toHaveAttribute('aria-disabled', 'true')
  // Still reachable by the keyboard, which then shows why.
  act(() => disabled.focus())
  expect(disabled).toHaveFocus()
  expect(await screen.findByRole('tooltip')).toHaveTextContent('Not made in a session')
  // Pressing it does nothing.
  fireEvent.click(disabled)
  expect(disabled).toHaveFocus()
})

// The widget page

test('the widget page previews the run named in its address, or one run of its own', async () => {
  reads.length = 0
  let started = 0
  serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/widgets/w1': map,
    'GET /api/operators/op_t/lineage': lineage,
    'GET /api/projects/p1/sources': projectSources,
    'POST /api/projects/p1/runs': () => json(run(`r${++started + 4}`), 201),
    'GET /api/runs/r2': run('r2'),
    'GET /api/runs/r5': run('r5'),
    'GET /api/runs/r2/operators/op_t/rows': () => {
      reads.push('r2')
      return rows('op_t', 1, false)
    },
    'GET /api/runs/r5/operators/op_t/rows': () => {
      reads.push('r5')
      return rows('op_t', 1, false)
    },
  })
  const { router } = renderAt('/projects/p1/widgets/w1?run=r2')

  let { dialog } = await openPipeline()
  expect(dialog).toHaveAccessibleDescription(/^Frozen: the run named in this page’s address, run r2\./)
  await within(dialog).findByText('op_t-0')
  expect(started).toBe(0)
  fireEvent.keyDown(dialog, { key: 'Escape' })

  await act(() => router.navigate({ to: '/projects/$projectId/widgets/$widgetId', params: { projectId: 'p1', widgetId: 'w1' } }))
  expect(await screen.findByTitle('Widget: Screening by county')).toHaveAttribute(
    'src',
    'http://localhost:5174/map.html#widget=w1&run=r5',
  )
  ;({ dialog } = await openPipeline())
  expect(dialog).toHaveAccessibleDescription('This page’s current run, follows new data (run r5).')
  await within(dialog).findByText('op_t-0')
  expect(reads).toEqual(['r2', 'r5'])
  expect(started).toBe(1)
})
