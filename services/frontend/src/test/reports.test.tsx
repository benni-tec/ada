import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import type { Operator, Report, ReportSource, ReportVersion } from '@/lib/api'
import { effectsOf } from '@/lib/events'

import { claude, json, project, renderAt, serveApi, session, widget } from './app'

const chart = widget({ id: 'w1', type: 'line-chart', title: 'Coverage by region', operator_id: 'op_t' })
const value = widget({ id: 'w2', type: 'value', title: 'Latest coverage', operator_id: 'op_t' })

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

const sources: ReportSource[] = [
  {
    data_source_id: 'ds1',
    name: 'Sotkanet',
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
        {
          type: 'section',
          title: 'Trend',
          blocks: [{ type: 'widget', widget_id: 'w1', caption: 'By wellbeing services county' }],
        },
        { type: 'widget', widget_id: 'w2', caption: '' },
      ],
      sources,
    },
    template_id: null,
    dashboard_version_id: null,
    created_by: claude,
    created_at: '2026-11-03T09:00:00Z',
    ...overrides,
  }
}

const older = version({ id: 'v1', version: '1.0.0', run_id: 'r1', time_range: { start: null, end: null } })

function operator(overrides: Partial<Operator>): Operator {
  return {
    id: 'op_s',
    project_id: 'p1',
    kind: 'source',
    params: {},
    inputs: [],
    output: { kind: 'table', columns: [], roles: {}, derived: false },
    materializing: true,
    created_by: claude,
    created_at: '2026-11-01T09:07:00Z',
    ...overrides,
  } as Operator
}

function serveReport(overrides: Record<string, unknown> = {}) {
  return serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/reports/rep1': report,
    'GET /api/reports/rep1/versions': [older, version()],
    'GET /api/report-versions/v2/sources': sources,
    'GET /api/report-versions/v1/sources': sources,
    'GET /api/sessions/s1': session(),
    'GET /api/widgets/w1': chart,
    'GET /api/widgets/w2': value,
    'GET /api/operators/op_t/lineage': [
      operator({}),
      operator({
        id: 'op_t',
        kind: 'transform',
        params: { sql: 'SELECT region, value FROM input_0' },
        inputs: ['op_s'],
        materializing: false,
      }),
    ],
    ...overrides,
  })
}

test('shows the latest version with its widgets pinned to its run', async () => {
  serveReport()
  renderAt('/projects/p1/reports/rep1')

  expect(await screen.findByRole('heading', { level: 1, name: 'Screening findings' })).toBeInTheDocument()
  expect(screen.getByLabelText('Version')).toHaveValue('1.1.0')
  expect(screen.getByRole('option', { name: '1.1.0 (latest)' })).toBeInTheDocument()
  expect(screen.getByRole('option', { name: '1.0.0' })).toBeInTheDocument()

  // The tree: static blocks as words, widgets in frames at the version's run.
  expect(screen.getByRole('heading', { level: 2, name: 'Screening gap' })).toBeInTheDocument()
  expect(screen.getByText('Mostly in the north.')).toBeInTheDocument()
  expect(screen.getByRole('complementary', { name: 'Below target' })).toHaveTextContent('Finding')
  expect(screen.getByRole('region', { name: 'Trend' })).toBeInTheDocument()
  const frame = await screen.findByTitle('Widget: Coverage by region')
  expect(frame).toHaveAttribute('src', 'http://localhost:5174/line-chart.html#widget=w1&run=r2')
  expect(await screen.findByTitle('Widget: Latest coverage')).toHaveAttribute(
    'src',
    'http://localhost:5174/value.html#widget=w2&run=r2',
  )
  expect(screen.getByText('By wellbeing services county')).toBeInTheDocument()
  // Full size, it opens over the report at the report's run (WidgetModal).
  const open = within(screen.getByRole('article', { name: 'Coverage by region' })).getByRole('link', { name: 'Open full size' })
  await waitFor(() => expect(open.getAttribute('href')).toMatch(/[?&]open=w1/))

  // What pins the numbers, and where they come from.
  const facts = screen.getByRole('complementary', { name: 'About this version' })
  expect(facts).toHaveTextContent('Data period2024-01-01 – 2024-12-31')
  expect(facts).toHaveTextContent('Runr2')
  expect(within(facts).getByText('External agent:', { exact: false })).toBeInTheDocument()
  const source = await within(facts).findByRole('listitem')
  expect(source).toHaveTextContent('Sotkanet')
  expect(within(source).getByRole('link', { name: 'https://sotkanet.test/3621.csv' })).toBeInTheDocument()
  expect(within(source).getByRole('time')).toHaveAttribute('dateTime', '2026-10-30T07:00:00Z')
  expect(source).toHaveTextContent('content abcdef012345')
  await waitFor(() => expect(source).toHaveTextContent('Used by “Coverage by region”, “Latest coverage”'))

  expect(screen.getByRole('link', { name: 'Why did coverage drop?' })).toHaveAttribute(
    'href',
    '/projects/p1/sessions/s1',
  )
})

test('a report says its numbers are frozen instead of claiming to be live', async () => {
  serveReport()
  renderAt('/projects/p1/reports/rep1')

  expect(await screen.findByText(/Frozen at version 1\.1\.0: these numbers never change\./)).toBeInTheDocument()
  expect(await screen.findByText(/Data fetched/)).toBeInTheDocument()
  expect(screen.queryByLabelText(/Live updates/)).not.toBeInTheDocument()

  // Its type is said above its title, where the breadcrumbs were.
  expect(document.querySelector('[data-page-type="report"]')).toHaveTextContent('Report')
  expect(screen.getByRole('heading', { level: 1, name: 'Screening findings' })).toBeInTheDocument()
})

test('opening a report names its latest version in the address', async () => {
  // So a version created while someone reads does not swap the numbers under them.
  serveReport()
  const { router } = renderAt('/projects/p1/reports/rep1')

  await waitFor(() => expect(router.state.location.search).toEqual({ version: '1.1.0' }))
})

test('shows an older version and points to the latest', async () => {
  serveReport()
  const { router } = renderAt('/projects/p1/reports/rep1?version=1.0.0')

  expect(await screen.findByLabelText('Version')).toHaveValue('1.0.0')
  expect(await screen.findByTitle('Widget: Coverage by region')).toHaveAttribute(
    'src',
    'http://localhost:5174/line-chart.html#widget=w1&run=r1',
  )
  expect(screen.getByRole('complementary', { name: 'About this version' })).toHaveTextContent(
    'Data periodAll periods',
  )
  expect(screen.getByText(/You are reading version 1.0.0/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: '1.1.0' })).toHaveAttribute('href', '/projects/p1/reports/rep1?version=1.1.0')

  fireEvent.change(screen.getByLabelText('Version'), { target: { value: '1.1.0' } })
  await waitFor(() => expect(router.state.location.search).toEqual({ version: '1.1.0' }))
  expect(await screen.findByTitle('Widget: Coverage by region')).toHaveAttribute(
    'src',
    'http://localhost:5174/line-chart.html#widget=w1&run=r2',
  )
})

test('says so when the version does not exist', async () => {
  serveReport()
  renderAt('/projects/p1/reports/rep1?version=9.9.9')
  expect(await screen.findByRole('alert')).toHaveTextContent('This report has no version 9.9.9.')
})

test('every widget’s card opens its pipeline, and nothing of it is read until it is opened', async () => {
  const fetch = serveReport({ 'GET /api/projects/p1/sources': [] })
  renderAt('/projects/p1/reports/rep1')

  const card = await screen.findByRole('article', { name: 'Coverage by region' })
  const opener = within(card).getByRole('button', { name: 'Pipeline' })
  const asked = () => fetch.mock.calls.map(([input]) => new URL(input instanceof Request ? input.url : String(input)).pathname)
  expect(asked().filter((path) => path.includes('/rows') || path.includes('/lineage') || path.startsWith('/api/runs/'))).toEqual([])

  fireEvent.click(opener)
  const dialog = await screen.findByRole('dialog', { name: 'Pipeline of “Coverage by region”' })
  fireEvent.click(await within(dialog).findByRole('button', { name: /^Source: Sotkanet/ }))
  // From the version's sources list: the address the data came from.
  expect(within(dialog).getByRole('complementary', { name: 'Details' })).toHaveTextContent(
    'https://sotkanet.test/3621.csv',
  )
})

test('the sidebar lists the project’s reports, newest first, and offers to generate one', async () => {
  serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/projects/p1/sessions': [session()],
    'GET /api/projects/p1/sources': [],
    'GET /api/projects/p1/reports': [
      report,
      { ...report, id: 'rep2', name: 'Monthly coverage', session_id: null, dashboard_id: 'd1', created_at: '2026-11-09T09:00:00Z' },
    ],
  })
  renderAt('/projects/p1')

  const nav = await screen.findByRole('navigation', { name: 'Project' })
  const reports = within(nav).getByRole('group', { name: 'Reports' })
  await waitFor(() => expect(within(reports).getAllByRole('link')).toHaveLength(3))
  expect(within(reports).getAllByRole('link').map((link) => link.textContent)).toEqual([
    '',
    'Monthly coverage',
    'Screening findings',
  ])
  expect(within(reports).getByRole('link', { name: 'Screening findings' })).toHaveAttribute('href', '/projects/p1/reports/rep1')
  expect(within(reports).getByRole('link', { name: 'Generate a report' })).toHaveAttribute('href', '/projects/p1/reports/new')
})

test('generates a report from a dashboard and opens it', async () => {
  const sent: unknown[] = []
  serveReport({
    'GET /api/projects/p1/dashboards': [
      { id: 'd1', project_id: 'p1', name: 'Coverage' },
      { id: 'd2', project_id: 'p1', name: 'Mortality' },
    ],
    'POST /api/dashboards/d2/reports': (body: unknown) => {
      sent.push(body)
      return json(version({ version: '1.0.0' }), 201)
    },
  })
  const { router } = renderAt('/projects/p1/reports/new?dashboard=d2')

  expect(await screen.findByLabelText('Dashboard')).toHaveValue('d2')
  fireEvent.change(screen.getByLabelText('Report name'), { target: { value: '  Mortality, monthly ' } })
  fireEvent.click(screen.getByRole('button', { name: 'Generate report' }))

  await waitFor(() => expect(sent).toEqual([{ name: 'Mortality, monthly' }]))
  await waitFor(() => expect(router.state.location.pathname).toBe('/projects/p1/reports/rep1'))
  expect(router.state.location.search).toEqual({ version: '1.0.0' })
})

test('says why a report was not generated', async () => {
  serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/projects/p1/dashboards': [{ id: 'd1', project_id: 'p1', name: 'Coverage' }],
    'POST /api/dashboards/d1/reports': json({ detail: 'Dashboard d1 shows no widgets' }, 422),
  })
  renderAt('/projects/p1/reports/new')

  fireEvent.change(await screen.findByLabelText('Dashboard'), { target: { value: 'd1' } })
  fireEvent.change(screen.getByLabelText('Report name'), { target: { value: 'Monthly' } })
  fireEvent.click(screen.getByRole('button', { name: 'Generate report' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Not generated: Dashboard d1 shows no widgets')
})

test('a new report version refreshes the project’s reports and the report', () => {
  const effects = effectsOf({
    type: 'report.version_created',
    project_id: 'p1',
    payload: { report_id: 'rep1', version_id: 'v3', version: '1.2.0' },
    at: '2026-11-04T10:00:00Z',
  })
  expect(effects).toEqual({
    invalidate: [
      ['projects', 'p1', 'reports'],
      ['reports', 'rep1'],
    ],
    reloadWidgets: false,
  })
})
