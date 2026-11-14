import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import type { Alert, AlertRule, AlertView, Operator } from '@/lib/api'
import { effectsOf } from '@/lib/events'
import { FakeEventSource, json, project, renderAt, serveApi } from '@/test/app'

import { AlertBadges } from './alert-badges'

// Sample records

const formula = {
  id: 'low',
  kind: 'compare',
  op: '<',
  args: [
    { id: 'v', kind: 'column', column: 'value' },
    { id: 'c', kind: 'constant', value: 80 },
  ],
}

function rule(overrides: Partial<AlertRule> = {}): AlertRule {
  return {
    id: 'r1',
    project_id: 'p1',
    dashboard_id: 'd1',
    name: 'Coverage below target',
    operator_id: 'op_measure',
    formula,
    key_columns: ['region'],
    severity: 'critical',
    check_interval_seconds: 3600,
    max_data_age_seconds: null,
    alert_pipeline_id: null,
    enabled: true,
    created_at: '2026-11-01T09:00:00Z',
    last_checked_at: '2026-11-02T09:00:00Z',
    revision: 1,
    ...overrides,
  }
}

function alert(overrides: Partial<Alert> = {}): Alert {
  return {
    id: 'a1',
    project_id: 'p1',
    rule_id: 'r1',
    key: { region: 'north' },
    state: 'firing',
    since_run_id: 'run-1',
    last_run_id: 'run-2',
    started_at: '2026-11-02T09:00:00Z',
    resolved_at: null,
    ...overrides,
  }
}

const dashboard = {
  id: 'd1',
  project_id: 'p1',
  name: 'Screening',
  current_version_id: null,
  default_time_range: { start: null, end: null },
  created_at: '2026-11-01T09:00:00Z',
  revision: 1,
}

const measure: Operator = {
  id: 'op_measure',
  project_id: 'p1',
  kind: 'transform',
  params: { sql: 'SELECT * FROM input_0' },
  inputs: ['op_source'],
  output: {
    kind: 'table',
    columns: [
      { name: 'region', type: 'text', nullable: true },
      { name: 'start', type: 'date', nullable: true },
      { name: 'end', type: 'date', nullable: true },
      { name: 'value', type: 'number', nullable: true },
    ],
    roles: { time: { start: 'start', end: 'end' }, geo: null, measures: [{ value: 'value' }] },
    derived: false,
  },
  materializing: false,
  created_by: { kind: 'user', name: 'web' },
  created_at: '2026-11-01T09:00:00Z',
} as Operator

const feed: AlertView[] = [
  { alert: alert(), rule: rule() },
  {
    alert: alert({ id: 'a2', key: { region: 'south' }, state: 'resolved', resolved_at: '2026-11-03T09:00:00Z' }),
    rule: rule({ severity: 'warning' }),
  },
]

const rows = {
  columns: [
    { name: 'region', type: 'text', nullable: true },
    { name: 'start', type: 'date', nullable: true },
    { name: 'value', type: 'number', nullable: true },
  ],
  rows: [
    ['north', '2023-01-01', 85],
    ['north', '2024-01-01', 70],
    ['south', '2024-01-01', 92],
  ],
  truncated: false,
}

function alertsApi(extra: Record<string, unknown> = {}) {
  return serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/projects/p1/alerts': (_body: unknown, request: Request) => {
      const state = new URL(request.url).searchParams.get('state')
      return state ? feed.filter((view) => view.alert.state === state) : feed
    },
    'GET /api/projects/p1/alert-rules': [{ dashboard, rules: [rule()] }],
    'GET /api/projects/p1/widgets': [],
    'GET /api/operators/op_measure': measure,
    'GET /api/runs/run-2/operators/op_measure/rows': rows,
    ...extra,
  })
}

// The feed

test('the feed shows firing alerts first with key, rule, severity and since when', async () => {
  alertsApi()
  renderAt('/projects/p1/alerts')

  const list = await screen.findByRole('list', { name: 'Alerts' })
  const items = within(list).getAllByRole('listitem')
  expect(items).toHaveLength(2)
  expect(items[0]).toHaveTextContent('Critical')
  expect(items[0]).toHaveTextContent('region: north')
  expect(items[0]).toHaveTextContent('Coverage below target')
  expect(items[0]).toHaveTextContent('Firing')
  expect(items[0]).toHaveTextContent(/Since/)
  expect(items[1]).toHaveTextContent('region: south')
  expect(items[1]).toHaveTextContent('Resolved')
})

test('the feed filters by state', async () => {
  const fetch = alertsApi()
  renderAt('/projects/p1/alerts')
  await screen.findByRole('list', { name: 'Alerts' })

  fireEvent.click(screen.getByRole('button', { name: 'Resolved' }))
  await waitFor(() => expect(within(screen.getByRole('list', { name: 'Alerts' })).getAllByRole('listitem')).toHaveLength(1))
  expect(screen.getByRole('button', { name: 'Resolved' })).toHaveAttribute('aria-pressed', 'true')
  const urls = fetch.mock.calls.map(([input]) => new Request(input as RequestInfo).url)
  expect(urls).toContainEqual(expect.stringContaining('/api/projects/p1/alerts?state=resolved'))
})

test('an alert opens the rows of its key in the run that showed it', async () => {
  alertsApi()
  renderAt('/projects/p1/alerts')
  const list = await screen.findByRole('list', { name: 'Alerts' })
  const first = within(list).getAllByRole('listitem')[0]

  const toggle = within(first).getByRole('button', { name: 'Show the data that fires' })
  fireEvent.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  const table = await within(first).findByRole('table')
  expect(within(table).getByText(/Rows for region: north in run/)).toBeInTheDocument()
  // Only the alert's key, with the history the time functions read.
  expect(within(table).getAllByRole('row')).toHaveLength(3)
  expect(within(table).queryByText('south')).not.toBeInTheDocument()
})

test('an alert with a recorded condition opens the rows that raised it', async () => {
  const raised = alert({ condition_operator_id: 'op_condition' })
  alertsApi({
    'GET /api/projects/p1/alerts': [{ alert: raised, rule: rule() }],
    'GET /api/runs/run-2/operators/op_condition/rows': {
      columns: [...rows.columns, { name: 'geometry', type: 'text', nullable: true }],
      rows: [['north', '2024-01-01', 70, `{"type":"Polygon","coordinates":[${'[1,2],'.repeat(40)}[1,2]]}`]],
      truncated: false,
    },
  })
  renderAt('/projects/p1/alerts')
  const list = await screen.findByRole('list', { name: 'Alerts' })

  fireEvent.click(within(list).getByRole('button', { name: 'Show the data that fires' }))
  const table = await within(list).findByRole('table')
  expect(within(table).getByText(/Alerting rows for region: north in run/)).toBeInTheDocument()
  expect(within(table).getAllByRole('row')).toHaveLength(2)
  expect(within(table).getByText('70')).toBeInTheDocument()
  // An outline is cut short, whole in its title.
  expect(within(table).getByText(/^\{"type":"Polygon".*…$/)).toHaveAttribute('title', expect.stringContaining('[1,2]]}'))
})

test('a live alert event refetches the feed', async () => {
  const fetch = alertsApi()
  renderAt('/projects/p1/alerts')
  await screen.findByRole('list', { name: 'Alerts' })
  const before = fetch.mock.calls.length

  act(() => FakeEventSource.latest().emit('alert.firing', { type: 'alert.firing', project_id: 'p1', payload: { alert_id: 'a3', rule_id: 'r1' }, at: '' }))
  await waitFor(() => expect(fetch.mock.calls.length).toBeGreaterThan(before))
  expect(effectsOf({ type: 'alert.resolved', project_id: 'p1', payload: {}, at: '' }).invalidate).toEqual([
    ['alerts'],
    ['alert-rules'],
  ])
})

// Rules

test('rules are listed per dashboard with their condition, and checked on request', async () => {
  alertsApi({
    'POST /api/alert-rules/r1/check': { rule: rule(), changed: [alert()], firing: [alert()] },
  })
  renderAt('/projects/p1/alerts')

  const rules = await screen.findByRole('list', { name: 'Rules of Screening' })
  const item = within(rules).getByRole('listitem')
  expect(item).toHaveTextContent('Coverage below target')
  expect(item).toHaveTextContent('value < 80')
  expect(item).toHaveTextContent('per region')
  expect(item).toHaveTextContent('every hour')

  fireEvent.click(within(item).getByRole('button', { name: 'Check now' }))
  expect(await within(item).findByRole('status')).toHaveTextContent('1 new, 0 resolved, 1 firing now')
})

test('a rule is built as a tree and created', async () => {
  let created: unknown = null
  alertsApi({
    'POST /api/dashboards/d1/alert-rules': (body: unknown) => {
      created = body
      return json(rule({ id: 'r2' }), 201)
    },
  })
  renderAt('/projects/p1/alerts')

  fireEvent.click(await screen.findByRole('button', { name: 'New rule' }))
  const form = screen.getByRole('form', { name: 'New alert rule' })
  fireEvent.change(within(form).getByLabelText('Name'), { target: { value: 'Falling coverage' } })
  fireEvent.change(within(form).getByLabelText('Measure operator id'), { target: { value: 'op_measure' } })
  fireEvent.click(await within(form).findByRole('checkbox', { name: 'region' }))

  // The default condition: the first number below 0.
  expect(within(form).getByLabelText('Condition')).toHaveTextContent('value < 0')
  fireEvent.change(within(form).getByLabelText('Value of n2'), { target: { value: '80' } })
  expect(within(form).getByLabelText('Condition')).toHaveTextContent('value < 80')

  // Nest the comparison in an "or" and add a second condition.
  fireEvent.change(within(form).getByLabelText('Nest root in'), { target: { value: 'or' } })
  const condition = within(form).getByLabelText('Condition')
  expect(condition).toHaveTextContent('value < 80 or value < 0')
  // The new operand compares the change over one period instead.
  fireEvent.change(within(form).getByLabelText('Nest n8 in'), { target: { value: 'change' } })
  expect(condition).toHaveTextContent('value < 80 or change(value, 1 period) < 0')
  // Reorder, then add and remove a third condition.
  fireEvent.click(within(form).getByRole('button', { name: 'Move root down' }))
  expect(condition).toHaveTextContent('change(value, 1 period) < 0 or value < 80')
  fireEvent.click(within(form).getByRole('button', { name: /Add a condition to/ }))
  expect(condition).toHaveTextContent('change(value, 1 period) < 0 or value < 80 or value < 0')
  const removes = within(form).getAllByRole('button', { name: /^Remove / })
  fireEvent.click(removes[removes.length - 1])
  expect(condition).toHaveTextContent('change(value, 1 period) < 0 or value < 80')

  fireEvent.change(within(form).getByLabelText('Check every (minutes)'), { target: { value: '60' } })
  fireEvent.click(within(form).getByRole('button', { name: 'Create rule' }))

  await waitFor(() => expect(created).not.toBeNull())
  expect(created).toMatchObject({
    name: 'Falling coverage',
    operator_id: 'op_measure',
    key_columns: ['region'],
    severity: 'warning',
    check_interval_seconds: 3600,
    max_data_age_seconds: null,
    formula: { kind: 'or', args: [{ kind: 'compare', args: [{ kind: 'change' }, {}] }, { id: 'root' }] },
  })
  await waitFor(() => expect(screen.queryByRole('form', { name: 'New alert rule' })).not.toBeInTheDocument())
})

test('a validation error from the server marks the node it names', async () => {
  alertsApi({
    'PATCH /api/alert-rules/r1': json({ detail: "Formula node 'c': cannot compare a text with a number" }, 422),
  })
  renderAt('/projects/p1/alerts')

  const rules = await screen.findByRole('list', { name: 'Rules of Screening' })
  fireEvent.click(within(rules).getByRole('button', { name: 'Edit' }))
  const form = await screen.findByRole('form', { name: 'Edit rule Coverage below target' })
  fireEvent.click(within(form).getByRole('button', { name: 'Save rule' }))

  expect(await within(form).findByRole('alert')).toHaveTextContent("Formula node 'c': cannot compare a text with a number")
  expect(within(form).getByRole('group', { name: 'Constant c' })).toHaveAttribute('aria-invalid', 'true')
  expect(within(form).getByRole('group', { name: 'Comparison low' })).not.toHaveAttribute('aria-invalid')
})

test('an edit sends the rule revision and the changed fields', async () => {
  let patched: unknown = null
  alertsApi({
    'PATCH /api/alert-rules/r1': (body: unknown) => {
      patched = body
      return rule({ revision: 2, enabled: false })
    },
  })
  renderAt('/projects/p1/alerts')
  const rules = await screen.findByRole('list', { name: 'Rules of Screening' })
  fireEvent.click(within(rules).getByRole('button', { name: 'Edit' }))
  const form = await screen.findByRole('form', { name: 'Edit rule Coverage below target' })
  fireEvent.click(within(form).getByRole('checkbox', { name: 'Enabled' }))
  fireEvent.change(within(form).getByLabelText('Operator of low'), { target: { value: '>=' } })
  // An emptied interval is sent as null, which clears it; key columns can change too.
  fireEvent.change(within(form).getByLabelText('Check every (minutes)'), { target: { value: '' } })
  fireEvent.change(within(form).getByLabelText('Maximum data age (minutes)'), { target: { value: '30' } })
  fireEvent.click(await within(form).findByRole('checkbox', { name: 'start' }))
  fireEvent.click(within(form).getByRole('button', { name: 'Save rule' }))

  await waitFor(() => expect(patched).not.toBeNull())
  expect(patched).toEqual({
    expected_revision: 1,
    name: 'Coverage below target',
    formula: { ...formula, op: '>=' },
    severity: 'critical',
    check_interval_seconds: null,
    max_data_age_seconds: 1800,
    key_columns: ['region', 'start'],
    enabled: false,
  })
})

test('a project without dashboards says where rules belong', async () => {
  alertsApi({ 'GET /api/projects/p1/alert-rules': [] })
  renderAt('/projects/p1/alerts')
  expect(await screen.findByText(/No dashboards yet/)).toBeInTheDocument()
})

// Badges and the project page

function renderBadges(dashboardId: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createRouter({
    routeTree: createRootRoute({ component: () => <AlertBadges dashboardId={dashboardId} /> }),
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

test('the badges count firing alerts by severity and link to the feed', async () => {
  serveApi({
    'GET /api/dashboards/d1/alerts': [
      { alert: alert(), rule: rule() },
      { alert: alert({ id: 'a3', key: { region: 'east' } }), rule: rule() },
      { alert: alert({ id: 'a4', key: { region: 'west' } }), rule: rule({ id: 'r2', severity: 'info' }) },
    ],
  })
  renderBadges('d1')

  const link = await screen.findByRole('link', { name: /3 firing alerts: 2 critical, 1 info/ })
  expect(link).toHaveAttribute('href', '/projects/p1/alerts')
  expect(link).toHaveTextContent('2Critical')
  expect(link).toHaveTextContent('1Info')
})

test('the badges say when nothing fires', async () => {
  serveApi({ 'GET /api/dashboards/d1/alerts': [] })
  renderBadges('d1')
  expect(await screen.findByRole('status')).toHaveTextContent('No alerts firing')
})

test('the sidebar counts the firing alerts beside the way to the feed', async () => {
  alertsApi({
    'GET /api/projects/p1/sessions': [],
    'GET /api/projects/p1/sources': [],
  })
  renderAt('/projects/p1')

  const nav = await screen.findByRole('navigation', { name: 'Project' })
  const link = within(nav).getByRole('link', { name: 'Alerts' })
  expect(link).toHaveAttribute('href', '/projects/p1/alerts')
  expect(await within(link.closest('li')!).findByText(/firing/)).toBeInTheDocument()
})
