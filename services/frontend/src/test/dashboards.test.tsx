import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import type { Dashboard, DashboardVersion, DashboardView } from '@/lib/api'
import { effectsOf } from '@/lib/events'

import { claude, FakeEventSource, json, project, renderAt, serveApi, session, web, widget } from './app'

function dashboard(overrides: Partial<Dashboard> = {}): Dashboard {
  return {
    id: 'd1',
    project_id: 'p1',
    name: 'Screening overview',
    current_version_id: 'v2',
    default_time_range: { start: '2020-01-01', end: '2024-12-31' },
    created_at: '2026-11-01T08:00:00Z',
    revision: 3,
    ...overrides,
  }
}

function slot(name: string, widgetId: string | null, x: number, y: number, w = 6, h = 4) {
  return { name, description: '', widget_id: widgetId, layout: { x, y, w, h } }
}

const v1: DashboardVersion = {
  id: 'v1',
  dashboard_id: 'd1',
  number: 1,
  slots: [slot('coverage', 'w1', 0, 0)],
  template_id: null,
  created_by: web,
  created_at: '2026-11-01T08:30:00Z',
}
const v2: DashboardVersion = {
  ...v1,
  id: 'v2',
  number: 2,
  slots: [slot('coverage', 'w1', 0, 0), slot('headline', 'w2', 6, 0), slot('notes', null, 0, 4, 12, 2)],
  created_by: claude,
  created_at: '2026-11-02T08:30:00Z',
}

const coverage = widget({ id: 'w1', title: 'Coverage by region', session_id: 's1' })
const headline = widget({ id: 'w2', type: 'value', title: 'Latest coverage', session_id: 's1' })

function run(id: string, range: { start: string | null; end: string | null }) {
  return { id, project_id: 'p1', time_range: range, bindings: {}, snapshots: {}, started_by: web, started_at: '2026-11-03T08:00:00Z' }
}

function view(overrides: Partial<DashboardView> = {}): DashboardView {
  return { dashboard: dashboard(), version: v2, ...overrides }
}

/** The bodies of the runs started, in order. */
const runBodies: unknown[] = []

function serveDashboard(overrides: Record<string, unknown> = {}) {
  let runs = 0
  runBodies.length = 0
  return serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/dashboards/d1': view(),
    'GET /api/dashboards/d1/versions': [v1, v2],
    'GET /api/projects/p1/widgets': [coverage, headline],
    'POST /api/dashboards/d1/runs': (body: unknown) => {
      runs += 1
      runBodies.push(body)
      return json(
        run(`r${runs}`, (body as { time_range: { start: string | null; end: string | null } }).time_range),
        201,
      )
    },
    ...overrides,
  })
}

const frameSrc = (title: string) => screen.findByTitle(title).then((frame) => frame.getAttribute('src'))

test('shows the slots on the grid, every widget reading the same run', async () => {
  serveDashboard()
  renderAt('/projects/p1/dashboards/d1')

  expect(await screen.findByRole('heading', { name: 'Screening overview', level: 1 })).toBeInTheDocument()
  const grid = await screen.findByRole('list', { name: 'Dashboard widgets' })
  const cells = within(grid).getAllByRole('listitem')
  expect(cells).toHaveLength(3)

  // The one run is started for the dashboard's own range, not an open one.
  expect(runBodies).toEqual([{ time_range: { start: '2020-01-01', end: '2024-12-31' } }])

  expect(await frameSrc('Widget: Coverage by region')).toBe('http://localhost:5174/line-chart.html#widget=w1&run=r1')
  expect(await frameSrc('Widget: Latest coverage')).toBe('http://localhost:5174/value.html#widget=w2&run=r1')

  // Positions come from the layout; an empty slot says so.
  expect(cells[1].style.getPropertyValue('--col')).toBe('7 / span 6')
  expect(cells[2].style.getPropertyValue('--row')).toBe('5 / span 2')
  expect(within(cells[2]).getByText(/Empty slot/)).toBeInTheDocument()
  expect(screen.getByText(/Showing 2020 to 2024 \(the dashboard’s default\)/)).toBeInTheDocument()
})

test('the header shows the dashboard’s firing alerts and links to a report from it', async () => {
  serveDashboard({
    'GET /api/dashboards/d1/alerts': [
      { alert: { id: 'a1', project_id: 'p1', rule_id: 'r1', state: 'firing' }, rule: { id: 'r1', severity: 'critical' } },
      { alert: { id: 'a2', project_id: 'p1', rule_id: 'r1', state: 'firing' }, rule: { id: 'r1', severity: 'critical' } },
    ],
  })
  renderAt('/projects/p1/dashboards/d1')

  const badges = await screen.findByRole('link', { name: /2 firing alerts: 2 critical/ })
  expect(badges).toHaveAttribute('href', '/projects/p1/alerts')
  expect(screen.getByRole('link', { name: 'Generate report' })).toHaveAttribute(
    'href',
    '/projects/p1/reports/new?dashboard=d1',
  )
})

test('a new time range starts a new run that all widgets then read', async () => {
  serveDashboard()
  renderAt('/projects/p1/dashboards/d1')
  expect(await frameSrc('Widget: Coverage by region')).toContain('run=r1')

  const form = screen.getByRole('form', { name: 'Time range' })
  fireEvent.change(within(form).getByLabelText('From year'), { target: { value: '2022' } })
  fireEvent.change(within(form).getByLabelText('To year'), { target: { value: '2022' } })
  fireEvent.click(within(form).getByRole('button', { name: 'Show' }))

  await waitFor(async () => expect(await frameSrc('Widget: Coverage by region')).toContain('run=r2'))
  expect(await frameSrc('Widget: Latest coverage')).toContain('run=r2')
  expect(runBodies).toEqual([
    { time_range: { start: '2020-01-01', end: '2024-12-31' } },
    { time_range: { start: '2022-01-01', end: '2022-12-31' } },
  ])
  expect(screen.getByText(/Showing 2022 · version 2/)).toBeInTheDocument()
})

test('refuses a range that ends before it starts', async () => {
  serveDashboard()
  renderAt('/projects/p1/dashboards/d1')
  const form = await screen.findByRole('form', { name: 'Time range' })

  fireEvent.change(within(form).getByLabelText('From year'), { target: { value: '2024' } })
  fireEvent.change(within(form).getByLabelText('To year'), { target: { value: '2020' } })

  expect(within(form).getByRole('alert')).toHaveTextContent('before the first')
  expect(within(form).getByRole('button', { name: 'Show' })).toBeDisabled()
})

test('saves the range as the dashboard’s default on its current revision', async () => {
  let sent: unknown
  serveDashboard({
    'PATCH /api/dashboards/d1': (body: unknown) => {
      sent = body
      return view({ dashboard: dashboard({ revision: 4, default_time_range: { start: '2018-01-01', end: null } }) })
    },
  })
  renderAt('/projects/p1/dashboards/d1')
  const form = await screen.findByRole('form', { name: 'Time range' })

  fireEvent.change(within(form).getByLabelText('From year'), { target: { value: '2018' } })
  fireEvent.change(within(form).getByLabelText('To year'), { target: { value: '' } })
  fireEvent.click(within(form).getByRole('button', { name: 'Save as default' }))

  await waitFor(() =>
    expect(sent).toEqual({ default_time_range: { start: '2018-01-01', end: null }, expected_revision: 3 }),
  )
  expect(await screen.findByText(/Showing 2018 onwards \(the dashboard’s default\)/)).toBeInTheDocument()
})

test('lists the versions and looks at an old one without changing the dashboard', async () => {
  serveDashboard()
  renderAt('/projects/p1/dashboards/d1?version=1')

  const history = await screen.findByRole('list', { name: 'Version history' })
  const items = within(history).getAllByRole('listitem')
  expect(items.map((item) => item.querySelector('span')?.textContent)).toEqual(['Version 2', 'Version 1'])
  expect(items[0]).toHaveTextContent('current')
  expect(items[0]).toHaveTextContent('External agent: ↗Claude Desktop')
  expect(items[1]).toHaveTextContent('1 slot')

  expect(await screen.findByText(/You are looking at version 1, not the current one/)).toBeInTheDocument()
  expect(within(await screen.findByRole('list', { name: 'Dashboard widgets' })).getAllByRole('listitem')).toHaveLength(1)
})

test('restoring a version adds a new one from its slots on the current revision', async () => {
  let sent: { slots: unknown[]; expected_revision: number } | undefined
  serveDashboard({
    'PUT /api/dashboards/d1/slots': (body: unknown) => {
      sent = body as typeof sent
      return view({ dashboard: dashboard({ revision: 4, current_version_id: 'v3' }), version: { ...v1, id: 'v3', number: 3 } })
    },
  })
  renderAt('/projects/p1/dashboards/d1')

  fireEvent.click(await screen.findByRole('button', { name: 'Restore version 1' }))

  await waitFor(() => expect(sent).toBeDefined())
  expect(sent).toEqual({ slots: v1.slots, expected_revision: 3 })
})

test('says so when someone else edited the dashboard first, and reads it again', async () => {
  let reads = 0
  serveDashboard({
    'GET /api/dashboards/d1': () => (reads += 1, view({ dashboard: dashboard({ revision: reads === 1 ? 3 : 4 }) })),
    'PUT /api/dashboards/d1/slots': () => json({ detail: 'conflict', expected_revision: 3, revision: 4 }, 409),
  })
  renderAt('/projects/p1/dashboards/d1')

  fireEvent.click(await screen.findByRole('button', { name: 'Restore version 1' }))

  const notice = await screen.findByText(/Someone else changed this dashboard/)
  expect(notice.closest('[role="alert"]')).toBeInTheDocument()
  await waitFor(() => expect(reads).toBeGreaterThan(1))
})

test('starts a session from the dashboard with it in the panel', async () => {
  const calls: unknown[] = []
  serveDashboard({
    'POST /api/projects/p1/sessions': (body: unknown) => {
      calls.push(['create', body])
      return json(session({ id: 's9', origin_dashboard_id: 'd1', title: 'Questions about Screening overview' }), 201)
    },
    'PATCH /api/sessions/s9': (body: unknown) => {
      calls.push(['panel', body])
      return session({ id: 's9', origin_dashboard_id: 'd1', panel_dashboard_id: 'd1', revision: 2 })
    },
    'GET /api/sessions/s9': session({ id: 's9', origin_dashboard_id: 'd1', panel_dashboard_id: 'd1', revision: 2 }),
    'GET /api/sessions/s9/entries': [],
    'GET /api/sessions/s9/widgets': [],
  })
  const { router } = renderAt('/projects/p1/dashboards/d1')

  fireEvent.click(await screen.findByRole('button', { name: 'Start a session from this dashboard' }))

  await waitFor(() => expect(router.state.location.pathname).toBe('/projects/p1/sessions/s9'))
  expect(calls).toEqual([
    ['create', { title: 'Questions about Screening overview', origin_dashboard_id: 'd1' }],
    ['panel', { panel_dashboard_id: 'd1', expected_revision: 1 }],
  ])
  expect(await screen.findByRole('complementary', { name: 'Dashboard' })).toBeInTheDocument()
})

test('shows a dashboard that has no version yet', async () => {
  serveDashboard({
    'GET /api/dashboards/d1': view({ dashboard: dashboard({ current_version_id: null }), version: null }),
    'GET /api/dashboards/d1/versions': [],
  })
  renderAt('/projects/p1/dashboards/d1')

  expect(await screen.findByText(/Nothing is pinned yet/)).toBeInTheDocument()
  expect(await screen.findByText(/No versions yet/)).toBeInTheDocument()
})

test('says when the dashboard does not exist', async () => {
  serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/dashboards/d1': json({ detail: 'dashboard d1 not found' }, 404),
    'GET /api/dashboards/d1/versions': json({ detail: 'dashboard d1 not found' }, 404),
    'GET /api/projects/p1/widgets': [],
  })
  renderAt('/projects/p1/dashboards/d1')

  expect(await screen.findByText(/dashboard d1 not found/)).toBeInTheDocument()
})

// The panel beside a session

function servePanel(overrides: Record<string, unknown> = {}) {
  return serveDashboard({
    'GET /api/sessions/s1': session({ panel_dashboard_id: 'd1' }),
    'GET /api/sessions/s1/entries': [],
    'GET /api/sessions/s1/widgets': [],
    ...overrides,
  })
}

test('the session panel shows the dashboard compactly, in reading order, on one run', async () => {
  servePanel()
  renderAt('/projects/p1/sessions/s1')

  const panel = await screen.findByRole('complementary', { name: 'Dashboard' })
  expect(await within(panel).findByRole('link', { name: 'Screening overview' })).toHaveAttribute(
    'href',
    '/projects/p1/dashboards/d1',
  )
  expect(within(panel).getByText(/2020 to 2024 · version 2/)).toBeInTheDocument()
  const cells = within(await within(panel).findByRole('list', { name: 'Dashboard widgets' })).getAllByRole('listitem')
  expect(cells.map((cell) => cell.querySelector('p')?.textContent)).toEqual(['coverage', 'headline', 'notes'])
  expect(await within(panel).findByTitle('Widget: Coverage by region')).toHaveAttribute(
    'src',
    'http://localhost:5174/line-chart.html#widget=w1&run=r1',
  )
})

test('the session panel follows the dashboard when it changes', async () => {
  let current = view()
  servePanel({ 'GET /api/dashboards/d1': () => current })
  renderAt('/projects/p1/sessions/s1')
  const panel = await screen.findByRole('complementary', { name: 'Dashboard' })
  expect(await within(panel).findAllByRole('listitem')).toHaveLength(3)

  // An agent pins a fourth widget; the stream announces the new version.
  current = view({
    dashboard: dashboard({ revision: 4, current_version_id: 'v3' }),
    version: { ...v2, id: 'v3', number: 3, slots: [...v2.slots, slot('extra', 'w1', 6, 4)] },
  })
  act(() => {
    FakeEventSource.latest().emit('dashboard.changed', {
      type: 'dashboard.changed',
      project_id: 'p1',
      payload: { dashboard_id: 'd1', version_id: 'v3' },
      at: '2026-11-03T09:00:00Z',
    })
  })

  await waitFor(() => expect(within(panel).getAllByRole('listitem')).toHaveLength(4))
  expect(within(panel).getByText(/version 3/)).toBeInTheDocument()
})

// Pinning from a session

test('pins a widget of the session to a dashboard on the dashboard’s latest revision', async () => {
  let pinned: unknown
  serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/sessions/s1': session(),
    'GET /api/sessions/s1/entries': [
      { id: 'e1', session_id: 's1', kind: 'widget', text: '', ref: 'w1', actor: web, created_at: '2026-11-01T09:10:00Z' },
    ],
    'GET /api/sessions/s1/widgets': [coverage],
    'GET /api/projects/p1/dashboards': [dashboard(), dashboard({ id: 'd2', name: 'Other' })],
    'GET /api/dashboards/d1': view({ dashboard: dashboard({ revision: 7 }) }),
    'POST /api/dashboards/d1/pins': (body: unknown) => {
      pinned = body
      return json(view({ dashboard: dashboard({ revision: 8 }) }), 201)
    },
  })
  renderAt('/projects/p1/sessions/s1')

  const card = await screen.findByRole('article', { name: 'Coverage by region' })
  fireEvent.click(within(card).getByRole('button', { name: 'Pin to dashboard' }))
  const form = await within(card).findByRole('form', { name: 'Pin Coverage by region to a dashboard' })
  await waitFor(() => expect(within(form).getByLabelText('Dashboard')).not.toBeDisabled())
  fireEvent.change(within(form).getByLabelText('Slot name'), { target: { value: 'coverage' } })
  fireEvent.click(within(form).getByRole('button', { name: 'Pin' }))

  const done = await within(card).findByRole('status')
  expect(done).toHaveTextContent('Pinned to Screening overview')
  expect(within(done).getByRole('link', { name: 'Screening overview' })).toHaveAttribute(
    'href',
    '/projects/p1/dashboards/d1',
  )
  expect(pinned).toEqual({ widget_id: 'w1', slot: 'coverage', expected_revision: 7 })
})

test('pins to a new dashboard, created first', async () => {
  const calls: unknown[] = []
  serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/sessions/s1': session(),
    'GET /api/sessions/s1/entries': [
      { id: 'e1', session_id: 's1', kind: 'widget', text: '', ref: 'w1', actor: web, created_at: '2026-11-01T09:10:00Z' },
    ],
    'GET /api/sessions/s1/widgets': [coverage],
    'GET /api/projects/p1/dashboards': [],
    'POST /api/projects/p1/dashboards': (body: unknown) => {
      calls.push(['create', body])
      return json(dashboard({ id: 'd5', name: 'Fresh', revision: 1, current_version_id: null }), 201)
    },
    'POST /api/dashboards/d5/pins': (body: unknown) => {
      calls.push(['pin', body])
      return json(view({ dashboard: dashboard({ id: 'd5', name: 'Fresh', revision: 2 }) }), 201)
    },
  })
  renderAt('/projects/p1/sessions/s1')

  const card = await screen.findByRole('article', { name: 'Coverage by region' })
  fireEvent.click(within(card).getByRole('button', { name: 'Pin to dashboard' }))
  const form = await within(card).findByRole('form', { name: /Pin Coverage by region/ })
  fireEvent.change(await within(form).findByLabelText('Name of the new dashboard'), { target: { value: 'Fresh' } })
  fireEvent.click(within(form).getByRole('button', { name: 'Pin' }))

  expect(await within(card).findByRole('status')).toHaveTextContent('Pinned to Fresh')
  expect(calls).toEqual([
    ['create', { name: 'Fresh' }],
    ['pin', { widget_id: 'w1', slot: 'Coverage by region', expected_revision: 1 }],
  ])
})

test('shows why a pin failed', async () => {
  serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/sessions/s1': session(),
    'GET /api/sessions/s1/entries': [
      { id: 'e1', session_id: 's1', kind: 'widget', text: '', ref: 'w1', actor: web, created_at: '2026-11-01T09:10:00Z' },
    ],
    'GET /api/sessions/s1/widgets': [coverage],
    'GET /api/projects/p1/dashboards': [dashboard()],
    'GET /api/dashboards/d1': view(),
    'POST /api/dashboards/d1/pins': json({ detail: 'A slot needs a name' }, 422),
  })
  renderAt('/projects/p1/sessions/s1')

  const card = await screen.findByRole('article', { name: 'Coverage by region' })
  fireEvent.click(within(card).getByRole('button', { name: 'Pin to dashboard' }))
  await waitFor(() => expect(within(card).getByLabelText('Dashboard')).not.toBeDisabled())
  fireEvent.click(within(card).getByRole('button', { name: 'Pin' }))

  expect(await within(card).findByRole('alert')).toHaveTextContent('Not pinned: A slot needs a name')
})

// The project page

test('lists the project’s dashboards and creates one', async () => {
  let created: unknown
  serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/projects/p1/sessions': [],
    'GET /api/projects/p1/sources': [],
    'GET /api/projects/p1/widgets': [],
    'GET /api/projects/p1/dashboards': [dashboard()],
    'POST /api/projects/p1/dashboards': (body: unknown) => {
      created = body
      return json(dashboard({ id: 'd8', name: 'Mortality', current_version_id: null }), 201)
    },
    'GET /api/dashboards/d8': view({ dashboard: dashboard({ id: 'd8', name: 'Mortality' }), version: null }),
    'GET /api/dashboards/d8/versions': [],
  })
  const { router } = renderAt('/projects/p1')

  const section = await screen.findByRole('region', { name: 'Dashboards' })
  const link = await within(section).findByRole('link', { name: /Screening overview/ })
  expect(link).toHaveAttribute('href', '/projects/p1/dashboards/d1')
  expect(link).toHaveTextContent('2020 to 2024')

  fireEvent.change(within(section).getByLabelText('New dashboard'), { target: { value: 'Mortality' } })
  fireEvent.click(within(section).getByRole('button', { name: 'Create dashboard' }))

  await waitFor(() => expect(router.state.location.pathname).toBe('/projects/p1/dashboards/d8'))
  expect(created).toEqual({ name: 'Mortality' })
})

// The live stream

test('a dashboard event refreshes the dashboard and the project’s list', () => {
  const effects = effectsOf({
    type: 'dashboard.changed',
    project_id: 'p1',
    payload: { dashboard_id: 'd1', version_id: 'v2' },
    at: '2026-11-03T09:00:00Z',
  })
  expect(effects.invalidate).toEqual([
    ['projects', 'p1', 'dashboards'],
    ['dashboards', 'd1'],
  ])
  expect(effects.reloadWidgets).toBe(false)
})
