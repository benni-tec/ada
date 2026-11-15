import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import type { Alert, AlertRule, AlertView, Operator } from '@/lib/api'

import { emit, json, project, renderAt, serveApi } from './app'

// The alerts page: the feed with each alert's rows, and the rules with their formula builder.

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

// The resolved alert recorded the condition that raised it.
const feed: AlertView[] = [
  { alert: alert(), rule: rule() },
  {
    alert: alert({
      id: 'a2',
      key: { region: 'south' },
      state: 'resolved',
      resolved_at: '2026-11-03T09:00:00Z',
      condition_sql: 'SELECT * FROM input_0 WHERE value < 80',
    }),
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
    'GET /api/alerts/a1/rows': rows,
    'GET /api/alerts/a2/rows': {
      columns: [...rows.columns, { name: 'geometry', type: 'text', nullable: true }],
      rows: [['south', '2024-01-01', 70, `{"type":"Polygon","coordinates":[${'[1,2],'.repeat(40)}[1,2]]}`]],
      truncated: false,
    },
    ...extra,
  })
}

// The feed

test('one card per dashboard, its rules in a table, each opening to its alerts and those to their data; filtered by state, refetched on a live event', async () => {
  const fetch = alertsApi()
  renderAt('/projects/p1/alerts')

  // The project's alerts are its dashboards': one card each, named after it.
  const section = await screen.findByRole('region', { name: 'Screening' })
  expect(within(section).getByRole('link', { name: 'Screening' })).toHaveAttribute('href', '/projects/p1/dashboards/d1')
  expect(section).toHaveTextContent('1 active')
  expect(section).not.toHaveTextContent(/firing/i)
  const rules = within(section).getByRole('table', { name: 'Rules of Screening' })
  const [, ruleRow] = within(rules).getAllByRole('row')
  expect(ruleRow).toHaveTextContent('Critical')
  expect(ruleRow).toHaveTextContent('Coverage below target')
  expect(ruleRow).toHaveTextContent('1 active')

  // A rule with an active alert starts open: its alerts, a table in its row.
  expect(within(ruleRow).getByRole('button', { name: 'Hide its alerts' })).toHaveAttribute('aria-expanded', 'true')
  const alerts = within(section).getByRole('table', { name: 'Alerts of Coverage below target' })
  const [head, active, ended] = within(alerts).getAllByRole('row')
  // A column per key column, its value in each row.
  expect(within(head).getAllByRole('columnheader')[0]).toHaveTextContent('region')
  expect(within(active).getAllByRole('cell')[0]).toHaveTextContent(/^north$/)
  expect(active).toHaveTextContent('Active')
  expect(within(ended).getAllByRole('cell')[0]).toHaveTextContent(/^south$/)
  expect(ended).toHaveTextContent('Ended')

  // The rows of its key in the run that showed it, with the history the time functions read.
  const toggle = within(active).getByRole('button', { name: 'Show the data behind it' })
  fireEvent.click(toggle)
  expect(toggle).toHaveAttribute('aria-expanded', 'true')
  let table = await screen.findByRole('table', { name: /^Rows for region: north in run/ })
  expect(within(table).getAllByRole('row')).toHaveLength(3)
  expect(within(table).queryByText('south')).not.toBeInTheDocument()

  // With a recorded condition: the rows behind it. An outline is cut short, whole in its title.
  fireEvent.click(within(ended).getByRole('button', { name: 'Show the data it last showed on' }))
  table = await screen.findByRole('table', { name: /^The rows behind it for region: south in run/ })
  expect(within(table).getAllByRole('row')).toHaveLength(2)
  expect(within(table).getByText(/^\{"type":"Polygon".*…$/)).toHaveAttribute('title', expect.stringContaining('[1,2]]}'))

  fireEvent.click(screen.getByRole('button', { name: 'Ended' }))
  await waitFor(() => expect(within(screen.getByRole('table', { name: 'Rules of Screening' })).getByRole('row', { name: /1 ended/ })).toBeInTheDocument())
  expect(screen.getByRole('button', { name: 'Ended' })).toHaveAttribute('aria-pressed', 'true')
  const urls = () => fetch.mock.calls.map(([input]) => new Request(input as RequestInfo).url)
  expect(urls()).toContainEqual(expect.stringContaining('/api/projects/p1/alerts?state=resolved'))

  const before = fetch.mock.calls.length
  act(() => emit('alert.firing', { alert_id: 'a3', rule_id: 'r1' }))
  await waitFor(() => expect(fetch.mock.calls.length).toBeGreaterThan(before))
})

// Rules

test('rules are listed per dashboard and checked on request; an edit sends the revision and the changed fields', async () => {
  const patched: unknown[] = []
  alertsApi({
    'POST /api/alert-rules/r1/check': { rule: rule(), changed: [alert()], firing: [alert()] },
    'PATCH /api/alert-rules/r1': (body: unknown) => {
      patched.push(body)
      if (patched.length === 1) return json({ detail: "Formula node 'c': cannot compare a text with a number" }, 422)
      return rule({ revision: 2, enabled: false })
    },
  })
  renderAt('/projects/p1/alerts')

  const rules = await screen.findByRole('table', { name: 'Rules of Screening' })
  const item = within(rules).getAllByRole('row')[1]
  expect(item).toHaveTextContent('Coverage below target')
  expect(item).toHaveTextContent('value < 80')
  expect(item).toHaveTextContent('per region')
  expect(item).toHaveTextContent('every hour')
  fireEvent.click(within(item).getByRole('button', { name: 'Check now' }))
  expect(await within(item).findByRole('status')).toHaveTextContent('1 new, 0 ended, 1 active now')

  fireEvent.click(within(rules).getByRole('button', { name: 'Edit' }))
  const form = await screen.findByRole('form', { name: 'Edit rule Coverage below target' })
  // The server's validation error marks the node it names.
  fireEvent.click(within(form).getByRole('button', { name: 'Save rule' }))
  expect(await within(form).findByRole('alert')).toHaveTextContent("Formula node 'c': cannot compare a text with a number")
  expect(within(form).getByRole('group', { name: 'Constant c' })).toHaveAttribute('aria-invalid', 'true')
  expect(within(form).getByRole('group', { name: 'Comparison low' })).not.toHaveAttribute('aria-invalid')

  fireEvent.click(within(form).getByRole('checkbox', { name: 'Enabled' }))
  fireEvent.change(within(form).getByLabelText('Operator of low'), { target: { value: '>=' } })
  // An emptied interval is sent as null, which clears it; key columns can change too.
  fireEvent.change(within(form).getByLabelText('Check every (minutes)'), { target: { value: '' } })
  fireEvent.change(within(form).getByLabelText('Maximum data age (minutes)'), { target: { value: '30' } })
  fireEvent.click(await within(form).findByRole('checkbox', { name: 'start' }))
  fireEvent.click(within(form).getByRole('button', { name: 'Save rule' }))
  await waitFor(() => expect(patched).toHaveLength(2))
  expect(patched[1]).toEqual({
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
