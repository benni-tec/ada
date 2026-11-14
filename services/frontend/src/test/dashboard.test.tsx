import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import type { DashboardSlot, DashboardVersion, DashboardView, Operator } from '@/lib/api'

import {
  claude,
  dashboard,
  emit,
  entry,
  json,
  models,
  pipeline,
  project,
  renderAt,
  run,
  serveApi,
  session,
  slot,
  turn,
  web,
  widget,
} from './app'

// A dashboard: its slots on the grid at one run, the time range, versions, arranging the
// layout, the agent panel, widgets full size, and the dashboard beside a session.

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

// Pinned copies: no session of their own, `copied_from` the original.
const coverage = widget({ id: 'w1', type: 'map', title: 'Coverage by region', session_id: null, copied_from: 'w0', operator_id: 'op_t' })
const headline = widget({ id: 'w2', type: 'value', title: 'Latest coverage', session_id: null, copied_from: 'w9' })
const original = widget({ id: 'w0', type: 'map', title: 'Coverage by region', session_id: 's4' })
const orphan = widget({ id: 'w9', type: 'value', title: 'Latest coverage', session_id: null })

const view = (overrides: Partial<DashboardView> = {}): DashboardView => ({ dashboard: dashboard(), version: v2, ...overrides })

const measure = {
  id: 'op_t',
  project_id: 'p1',
  kind: 'transform',
  params: { sql: 'SELECT * FROM input_0' },
  inputs: [],
  output: { kind: 'table', columns: [], roles: { measures: [] }, derived: true },
  materializing: false,
  created_by: web,
  created_at: '2026-11-01T09:07:00Z',
} as Operator

/** The bodies of the dashboard's runs, in order. */
const runBodies: unknown[] = []

function serveDashboard(overrides: Record<string, unknown> = {}) {
  runBodies.length = 0
  return serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/dashboards/d1': view(),
    'GET /api/dashboards/d1/versions': [v1, v2],
    'GET /api/projects/p1/widgets': [coverage, headline],
    'GET /api/widgets/w0': original,
    'GET /api/widgets/w9': orphan,
    'GET /api/widgets/w1': coverage,
    'POST /api/dashboards/d1/runs': (body: { time_range: { start: string | null; end: string | null } }) => {
      runBodies.push(body)
      return json(run(`r${runBodies.length}`, { time_range: body.time_range }), 201)
    },
    'GET /api/llm/models': models(),
    'GET /api/projects/p1/pipelines': [pipeline()],
    ...overrides,
  })
}

const grid = () => screen.findByRole('list', { name: 'Dashboard widgets' })
const frameSrc = (title: string) => screen.findByTitle(title).then((frame) => frame.getAttribute('src'))
const layoutOf = (body: unknown) => Object.fromEntries((body as { slots: DashboardSlot[] }).slots.map((item) => [item.name, item.layout]))

test('the slots on the grid all read one run of the dashboard’s range, which the time range control changes', async () => {
  let patched: unknown
  serveDashboard({
    'GET /api/dashboards/d1/alerts': [
      { alert: { id: 'a1', project_id: 'p1', rule_id: 'r1', state: 'firing' }, rule: { id: 'r1', severity: 'critical' } },
      { alert: { id: 'a2', project_id: 'p1', rule_id: 'r1', state: 'firing' }, rule: { id: 'r1', severity: 'critical' } },
    ],
    'PATCH /api/dashboards/d1': (body: unknown) => {
      patched = body
      return view({ dashboard: dashboard({ revision: 4, default_time_range: { start: '2018-01-01', end: null } }) })
    },
  })
  renderAt('/projects/p1/dashboards/d1')

  expect(await screen.findByRole('heading', { name: 'Screening overview', level: 1 })).toBeInTheDocument()
  const cells = within(await grid()).getAllByRole('listitem')
  expect(cells).toHaveLength(3)
  expect(await frameSrc('Widget: Coverage by region')).toBe('http://localhost:5174/map.html#widget=w1&run=r1')
  expect(await frameSrc('Widget: Latest coverage')).toBe('http://localhost:5174/value.html#widget=w2&run=r1')
  expect(runBodies).toEqual([{ time_range: { start: '2020-01-01', end: '2024-12-31' } }])
  // Positions come from the layout; an empty slot says so.
  expect(cells[1].style.getPropertyValue('--col')).toBe('7 / span 6')
  expect(cells[2].style.getPropertyValue('--row')).toBe('5 / span 2')
  expect(within(cells[2]).getByText(/Empty slot/)).toBeInTheDocument()
  expect(screen.getByText(/Showing 2020 to 2024 \(the dashboard’s default\)/)).toBeInTheDocument()

  // The header: active alerts by severity, and a report from this dashboard.
  expect(await screen.findByRole('link', { name: /2 active alerts: 2 critical/ })).toHaveAttribute('href', '/projects/p1/alerts')
  expect(screen.getByRole('link', { name: 'Generate report' })).toHaveAttribute('href', '/projects/p1/reports/new?dashboard=d1')

  // A range that ends before it starts is refused; a new one starts a run every widget reads.
  const form = screen.getByRole('form', { name: 'Time range' })
  fireEvent.change(within(form).getByLabelText('From year'), { target: { value: '2024' } })
  fireEvent.change(within(form).getByLabelText('To year'), { target: { value: '2020' } })
  expect(within(form).getByRole('alert')).toHaveTextContent('before the first')
  expect(within(form).getByRole('button', { name: 'Show' })).toBeDisabled()
  fireEvent.change(within(form).getByLabelText('From year'), { target: { value: '2022' } })
  fireEvent.change(within(form).getByLabelText('To year'), { target: { value: '2022' } })
  fireEvent.click(within(form).getByRole('button', { name: 'Show' }))
  await waitFor(async () => expect(await frameSrc('Widget: Coverage by region')).toContain('run=r2'))
  expect(await frameSrc('Widget: Latest coverage')).toContain('run=r2')
  expect(runBodies.at(-1)).toEqual({ time_range: { start: '2022-01-01', end: '2022-12-31' } })

  // Saved as the default, on the dashboard's current revision.
  const again = screen.getByRole('form', { name: 'Time range' })
  fireEvent.change(within(again).getByLabelText('From year'), { target: { value: '2018' } })
  fireEvent.change(within(again).getByLabelText('To year'), { target: { value: '' } })
  fireEvent.click(within(again).getByRole('button', { name: 'Save as default' }))
  await waitFor(() => expect(patched).toEqual({ default_time_range: { start: '2018-01-01', end: null }, expected_revision: 3 }))
  expect(await screen.findByText(/Showing 2018 onwards \(the dashboard’s default\)/)).toBeInTheDocument()
})

test('an old version is shown without changing the dashboard, and restoring it adds a new version', async () => {
  let restored: unknown
  serveDashboard({
    'PUT /api/dashboards/d1/slots': (body: unknown) => {
      restored = body
      return view({ dashboard: dashboard({ revision: 4, current_version_id: 'v3' }), version: { ...v1, id: 'v3', number: 3 } })
    },
  })
  renderAt('/projects/p1/dashboards/d1?version=1')

  const history = await screen.findByRole('list', { name: 'Version history' })
  const items = within(history).getAllByRole('listitem')
  expect(items.map((item) => item.querySelector('span')?.textContent)).toEqual(['Version 2', 'Version 1'])
  expect(items[0]).toHaveTextContent('current')
  expect(items[0]).toHaveTextContent('External agent: ↗Claude Desktop')
  expect(await screen.findByText(/You are looking at version 1, not the current one/)).toBeInTheDocument()
  expect(within(await grid()).getAllByRole('listitem')).toHaveLength(1)
  // An old version cannot be arranged.
  expect(screen.queryByRole('button', { name: 'Edit layout' })).not.toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Restore version 1' }))
  await waitFor(() => expect(restored).toEqual({ slots: v1.slots, expected_revision: 3 }))
})

// jsdom measures nothing, so the grid is taken as 1200 px wide: columns of 85⅓ px, 16 px
// apart, rows of 80 px. One column further is 101⅓ px, one row 96 px.
const COLUMN = 1200 / 12 - 16 + 16 / 12 + 16
const ROW = 96

function drag(handle: HTMLElement, dx: number, dy: number) {
  fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 500, clientY: 300 })
  fireEvent.pointerMove(handle, { pointerId: 1, clientX: 500 + dx, clientY: 300 + dy })
  fireEvent.pointerUp(handle, { pointerId: 1, clientX: 500 + dx, clientY: 300 + dy })
}

test('“Edit layout”: drags move or resize slots in a draft, Done saves it as one version, leaving asks, a conflict keeps it', async () => {
  const saved: unknown[] = []
  let reads = 0
  let current = view()
  serveDashboard({
    'GET /api/dashboards/d1': () => (reads++, current),
    'PUT /api/dashboards/d1/slots': (body: { slots: DashboardSlot[]; expected_revision: number }) => {
      saved.push(body)
      // Someone else changed the dashboard before the second save.
      if (saved.length === 2) return json({ detail: 'conflict', expected_revision: body.expected_revision, revision: 9 }, 409)
      const revision = current.dashboard.revision + 1
      current = view({ dashboard: dashboard({ revision, current_version_id: `v${revision}` }), version: { ...v2, id: `v${revision}`, number: revision, slots: body.slots } })
      return current
    },
  })
  const { router } = renderAt('/projects/p1/dashboards/d1')

  await grid()
  expect(screen.queryByRole('button', { name: 'Move headline' })).not.toBeInTheDocument()
  fireEvent.click(await screen.findByRole('button', { name: 'Edit layout' }))

  // The number moves left, where the map was: the map and the notes move down. The map,
  // three columns wider, keeps its shape and grows taller with it. Nothing is saved yet.
  drag(screen.getByRole('button', { name: 'Move headline' }), -6 * COLUMN, 0)
  drag(screen.getByRole('button', { name: 'Resize coverage' }), 3 * COLUMN, 0)
  expect(await screen.findByText(/unsaved layout changes/)).toBeInTheDocument()
  expect(saved).toEqual([])

  // Leaving with unsaved changes asks first; declined, the page stays.
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  // A blocked navigation never settles, so it is not awaited.
  act(() => void router.navigate({ to: '/projects/$projectId', params: { projectId: 'p1' } }))
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce())
  expect(router.state.location.pathname).toBe('/projects/p1/dashboards/d1')
  confirm.mockRestore()

  // Done: both changes, one version.
  fireEvent.click(screen.getByRole('button', { name: 'Done' }))
  await waitFor(() => expect(saved).toHaveLength(1))
  expect(saved[0]).toMatchObject({ expected_revision: 3 })
  expect(layoutOf(saved[0])).toEqual({
    coverage: { x: 0, y: 4, w: 9, h: 6 },
    headline: { x: 0, y: 0, w: 6, h: 4 },
    notes: { x: 0, y: 10, w: 12, h: 2 },
  })
  expect(await screen.findByText(/version 4/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Move coverage' })).not.toBeInTheDocument()

  // Refused: the dashboard is read again and the person told; the draft and the editing
  // stay, and the × discards them.
  fireEvent.click(screen.getByRole('button', { name: 'Edit layout' }))
  const before = reads
  drag(screen.getByRole('button', { name: 'Move notes' }), 0, ROW)
  fireEvent.click(screen.getByRole('button', { name: 'Done' }))
  expect(await screen.findByText(/Someone else changed this dashboard/)).toBeInTheDocument()
  await waitFor(() => expect(reads).toBeGreaterThan(before))
  expect(screen.getByRole('listitem', { name: 'notes' }).style.getPropertyValue('--row')).toBe('12 / span 2')
  fireEvent.click(screen.getByRole('button', { name: 'Discard the layout changes' }))
  expect(screen.getByRole('listitem', { name: 'notes' }).style.getPropertyValue('--row')).toBe('11 / span 2')
  expect(screen.getByRole('button', { name: 'Edit layout' })).toBeInTheDocument()
})

test('the keyboard arranges too: Enter picks up, arrows move or resize, Enter drops, Escape puts back', async () => {
  const saved: unknown[] = []
  serveDashboard({
    'PUT /api/dashboards/d1/slots': (body: { slots: DashboardSlot[] }) => (saved.push(body), view({ version: { ...v2, slots: body.slots } })),
  })
  renderAt('/projects/p1/dashboards/d1')
  fireEvent.click(await screen.findByRole('button', { name: 'Edit layout' }))

  const move = await screen.findByRole('button', { name: 'Move coverage' })
  act(() => move.focus())
  fireEvent.keyDown(move, { key: 'Enter' })
  expect(move).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByText(/coverage picked up to move/)).toBeInTheDocument()
  fireEvent.keyDown(move, { key: 'ArrowDown' })
  fireEvent.keyDown(move, { key: 'ArrowDown' })
  expect(screen.getByText('coverage: column 1, row 3, 6 wide, 4 high.')).toBeInTheDocument()
  fireEvent.keyDown(move, { key: 'Escape' })
  expect(saved).toEqual([])
  expect(screen.getByRole('listitem', { name: 'coverage' }).style.getPropertyValue('--row')).toBe('1 / span 4')

  fireEvent.keyDown(move, { key: 'Enter' })
  fireEvent.keyDown(move, { key: 'ArrowRight' })
  fireEvent.keyDown(move, { key: 'Enter' })

  const resize = screen.getByRole('button', { name: 'Resize notes' })
  fireEvent.keyDown(resize, { key: ' ' })
  fireEvent.keyDown(resize, { key: 'ArrowUp' })
  fireEvent.keyDown(resize, { key: 'ArrowLeft' })
  fireEvent.keyDown(resize, { key: ' ' })
  expect(saved).toEqual([])
  fireEvent.click(screen.getByRole('button', { name: 'Done' }))

  await waitFor(() => expect(saved).toHaveLength(1))
  expect(layoutOf(saved[0]).coverage).toEqual({ x: 1, y: 0, w: 6, h: 4 })
  // An empty slot's minimum is 2 by 2.
  expect(layoutOf(saved[0]).notes).toMatchObject({ w: 11, h: 2 })
})

test('a pinned copy leads to the session of its original, or says it was not made in one; its pipeline reads the dashboard’s run', async () => {
  const reads: string[] = []
  serveDashboard({
    'GET /api/operators/op_t/lineage': [measure],
    'GET /api/projects/p1/sources': [],
    'GET /api/runs/r1': run('r1'),
    'GET /api/runs/r1/operators/op_t/rows': () => {
      reads.push('r1')
      return { columns: [{ name: 'region', type: 'text', nullable: true }], rows: [['north']], truncated: false }
    },
  })
  renderAt('/projects/p1/dashboards/d1')

  const map = await screen.findByRole('article', { name: 'Coverage by region' })
  const back = await within(map).findByRole('link', { name: 'Go to the session it came from' })
  expect(back).toHaveAttribute('href', '/projects/p1/sessions/s4?widget=w0')
  expect(within(map).queryByRole('button', { name: 'Add to dashboard' })).not.toBeInTheDocument()
  // An icon's name is its tooltip, on hover; Escape hides it.
  fireEvent.pointerMove(back)
  expect(await screen.findByRole('tooltip')).toHaveTextContent('Go to the session it came from')
  fireEvent.keyDown(back, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('tooltip')).not.toBeInTheDocument())

  // Disabled, the way back is still reached by the keyboard, which shows why.
  const number = screen.getByRole('article', { name: 'Latest coverage' })
  const disabled = await within(number).findByRole('button', { name: 'Not made in a session' })
  await waitFor(() => expect(disabled).toHaveAttribute('aria-disabled', 'true'))
  act(() => disabled.focus())
  expect(await screen.findByRole('tooltip')).toHaveTextContent('Not made in a session')

  // The pipeline previews the dashboard's run and starts none.
  fireEvent.click(within(map).getByRole('button', { name: 'Pipeline' }))
  const dialog = await screen.findByRole('dialog', { name: 'Pipeline of “Coverage by region”' })
  expect(dialog).toHaveAccessibleDescription('The dashboard’s current run, follows new data (run r1).')
  expect(await within(dialog).findByText('north')).toBeInTheDocument()
  expect(reads).toEqual(['r1'])
  expect(runBodies).toHaveLength(1)
})

test('the agent panel opens on the dashboard’s agent session, and “Add widget” hands it the pipeline, dashboard and slot', async () => {
  const opened: string[] = []
  const sent: unknown[] = []
  serveDashboard({
    'POST /api/dashboards/d1/agent-session': () => {
      opened.push('d1')
      return json(session({ id: 's7', title: 'Screening overview (agent)', origin_dashboard_id: 'd1', panel_dashboard_id: 'd1' }), 201)
    },
    'GET /api/sessions/s7/entries': [entry({ id: 'e1', session_id: 's7', text: 'Earlier question' })],
    'GET /api/sessions/s7/widgets': [],
    'POST /api/projects/p1/runs': json(run('r9'), 201),
    'POST /api/sessions/s7/messages': (body: unknown) => {
      sent.push(body)
      return json({ entry: entry({ id: 'e9', session_id: 's7' }), turn: turn({ id: 't9', session_id: 's7', status: 'queued' }) }, 201)
    },
    'GET /api/turns/t9': turn({ id: 't9', session_id: 's7', status: 'queued' }),
  })
  renderAt('/projects/p1/dashboards/d1')
  await grid()

  // Closed at first: looking at a dashboard creates no session.
  expect(screen.queryByRole('complementary', { name: 'Dashboard agent' })).not.toBeInTheDocument()
  expect(opened).toEqual([])
  fireEvent.click(screen.getByRole('button', { name: 'Open the agent panel' }))
  let panel = await screen.findByRole('complementary', { name: 'Dashboard agent' })
  expect(await within(panel).findByText('Earlier question')).toBeInTheDocument()
  expect(within(panel).getByRole('link', { name: 'Open as a session' })).toHaveAttribute('href', '/projects/p1/sessions/s7')
  fireEvent.click(within(panel).getByRole('button', { name: 'Close the agent panel' }))
  expect(screen.queryByRole('complementary', { name: 'Dashboard agent' })).not.toBeInTheDocument()
  expect(localStorage.getItem('ada-dashboard-agent-panel')).toBe('closed')

  // In an empty slot: that slot. The panel opens with the chip, and the focus in the composer.
  fireEvent.click(within(await screen.findByRole('listitem', { name: 'notes' })).getByRole('button', { name: 'Add widget' }))
  fireEvent.click(await screen.findByRole('option', { name: /Screening by county/ }))
  panel = await screen.findByRole('complementary', { name: 'Dashboard agent' })
  const composer = await within(panel).findByRole('form', { name: 'Write a message' })
  expect(within(composer).getByRole('list', { name: 'Context' })).toHaveTextContent('Pipeline: Screening by county → Screening overview, slot “notes”')
  await waitFor(() => expect(within(composer).getByLabelText('Message')).toHaveFocus())
  fireEvent.change(within(composer).getByLabelText('Message'), { target: { value: 'A map of this' } })
  fireEvent.keyDown(within(composer).getByLabelText('Message'), { key: 'Enter' })
  await waitFor(() =>
    expect(sent).toEqual([
      {
        text: 'A map of this',
        context: [
          { kind: 'pipeline', operator_id: 'op_p1' },
          { kind: 'dashboard', dashboard_id: 'd1', slot: 'notes' },
        ],
        model: 'gemini/flash',
      },
    ]),
  )
  expect(opened).toEqual(['d1'])

  // In the header: a new slot.
  const header = screen.getAllByRole('banner').find((element) => element.textContent?.includes('Screening overview'))!
  fireEvent.click(within(header).getByRole('button', { name: 'Add widget' }))
  fireEvent.click(await screen.findByRole('option', { name: /Screening by county/ }))
  expect(await within(composer).findByRole('list', { name: 'Context' })).toHaveTextContent('Pipeline: Screening by county → Screening overview, a new slot')
})

test('a widget opens full size over the page at its card’s run; Escape, back and × close it', async () => {
  let own = 0
  serveDashboard({ 'POST /api/projects/p1/runs': () => json(run(`own${++own}`), 201) })
  const { router } = renderAt('/projects/p1/dashboards/d1')

  const card = await screen.findByRole('article', { name: 'Coverage by region' })
  await within(card).findByTitle('Widget: Coverage by region')
  const page = screen.getByRole('list', { name: 'Dashboard widgets' })
  fireEvent.click(within(card).getByRole('link', { name: 'Open full size' }))
  await waitFor(() => expect(router.state.location.search).toEqual({ open: 'w1' }))
  let dialog = await screen.findByRole('dialog', { name: 'Coverage by region' })
  // The card's run, not a new one; the page beneath stays as it was.
  expect(await within(dialog).findByTitle('Widget: Coverage by region')).toHaveAttribute('src', 'http://localhost:5174/map.html#widget=w1&run=r1')
  fireEvent.keyDown(dialog, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(router.state.location.search).toEqual({})
  expect(screen.getByRole('list', { name: 'Dashboard widgets' })).toBe(page)

  // The browser's back closes it too.
  fireEvent.click(within(card).getByRole('link', { name: 'Open full size' }))
  await screen.findByRole('dialog', { name: 'Coverage by region' })
  act(() => router.history.back())
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(router.state.location.search).toEqual({})

  // A link straight to `?open=` has no card's run: the widget gets one of its own.
  await act(() => router.navigate({ to: '.', search: { open: 'w1' } }))
  dialog = await screen.findByRole('dialog', { name: 'Coverage by region' })
  expect(await within(dialog).findByTitle('Widget: Coverage by region')).toHaveAttribute('src', 'http://localhost:5174/map.html#widget=w1&run=own1')
  fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(router.state.location.search).toEqual({})
})

test('a session started from the dashboard has it beside the conversation, which follows it and can detach it', async () => {
  const calls: unknown[] = []
  let stored = session({ id: 's9', origin_dashboard_id: 'd1', title: 'Questions about Screening overview' })
  let current = view()
  serveDashboard({
    'GET /api/dashboards/d1': () => current,
    'POST /api/projects/p1/sessions': (body: unknown) => (calls.push(['create', body]), json(stored, 201)),
    'PATCH /api/sessions/s9': (body: { panel_dashboard_id: string | null }) => {
      calls.push(['panel', body])
      stored = { ...stored, panel_dashboard_id: body.panel_dashboard_id, revision: stored.revision + 1 }
      return stored
    },
    'GET /api/sessions/s9': () => stored,
    'GET /api/sessions/s9/entries': [],
    'GET /api/sessions/s9/widgets': [],
  })
  const { router } = renderAt('/projects/p1/dashboards/d1')

  fireEvent.click(await screen.findByRole('button', { name: 'Start a session from this dashboard' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/projects/p1/sessions/s9'))

  // Half and half: the conversation, and the dashboard under a black bar with its name.
  const conversation = await screen.findByRole('region', { name: 'Conversation' })
  const panel = await screen.findByRole('complementary', { name: 'Dashboard' })
  expect(conversation.parentElement).toBe(panel.parentElement)
  const bar = panel.querySelector('header')!
  expect(bar).toHaveClass('bg-black', 'text-white')
  expect(await within(bar).findByRole('link', { name: 'Screening overview' })).toHaveAttribute('href', '/projects/p1/dashboards/d1')
  expect(await within(panel).findByText(/2020 to 2024 · version 2/)).toBeInTheDocument()
  expect(within(await within(panel).findByRole('list', { name: 'Dashboard widgets' })).getAllByRole('listitem').map((cell) => cell.getAttribute('aria-label'))).toEqual(['coverage', 'headline', 'notes'])
  expect(await within(panel).findByTitle('Widget: Coverage by region')).toHaveAttribute('src', 'http://localhost:5174/map.html#widget=w1&run=r1')

  // An empty slot offers "Add widget" into the session's composer, with the dashboard and slot.
  fireEvent.click(within(within(panel).getByRole('listitem', { name: 'notes' })).getByRole('button', { name: 'Add widget' }))
  fireEvent.click(await screen.findByRole('option', { name: /Screening by county/ }))
  const composer = screen.getByRole('form', { name: 'Write a message' })
  expect(await within(composer).findByRole('list', { name: 'Context' })).toHaveTextContent('Pipeline: Screening by county → Screening overview, slot “notes”')
  expect(within(composer).getByLabelText('Message')).toHaveFocus()

  // An agent pins a fourth widget; the stream announces the new version.
  current = view({ dashboard: dashboard({ revision: 4, current_version_id: 'v3' }), version: { ...v2, id: 'v3', number: 3, slots: [...v2.slots, slot('extra', 'w1', 6, 4)] } })
  act(() => emit('dashboard.changed', { dashboard_id: 'd1', version_id: 'v3' }))
  await waitFor(() => expect(within(panel).getAllByRole('listitem')).toHaveLength(4))

  // The × detaches it, and the conversation takes the full width.
  fireEvent.click(within(bar).getByRole('button', { name: 'Detach the dashboard' }))
  await waitFor(() => expect(screen.queryByRole('complementary', { name: 'Dashboard' })).not.toBeInTheDocument())
  expect(screen.getByRole('region', { name: 'Conversation' })).toBeInTheDocument()
  expect(calls).toEqual([
    ['create', { title: 'Questions about Screening overview', origin_dashboard_id: 'd1' }],
    ['panel', { panel_dashboard_id: 'd1', expected_revision: 1 }],
    ['panel', { panel_dashboard_id: null, expected_revision: 2 }],
  ])
})
