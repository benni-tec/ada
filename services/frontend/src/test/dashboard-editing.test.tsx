import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import type { Dashboard, DashboardSlot, DashboardVersion, DashboardView } from '@/lib/api'

import { entry, json, models, pipeline, project, renderAt, serveApi, session, turn, web, widget } from './app'

// Arranging a dashboard, its agent panel, its copies' way back, and widgets opened full size.

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

function slot(name: string, widgetId: string | null, x: number, y: number, w = 6, h = 4): DashboardSlot {
  return { name, description: '', widget_id: widgetId, layout: { x, y, w, h } }
}

const v2: DashboardVersion = {
  id: 'v2',
  dashboard_id: 'd1',
  number: 2,
  slots: [slot('coverage', 'w1', 0, 0), slot('headline', 'w2', 6, 0), slot('notes', null, 0, 4, 12, 2)],
  template_id: null,
  created_by: web,
  created_at: '2026-11-02T08:30:00Z',
}

// Pinned copies: no session of their own, `copied_from` the original.
const coverage = widget({ id: 'w1', type: 'map', title: 'Coverage by region', session_id: null, copied_from: 'w0' })
const headline = widget({ id: 'w2', type: 'value', title: 'Latest coverage', session_id: null, copied_from: 'w9' })
const original = widget({ id: 'w0', type: 'map', title: 'Coverage by region', session_id: 's4' })
const orphan = widget({ id: 'w9', type: 'value', title: 'Latest coverage', session_id: null })

function run(id: string) {
  return { id, project_id: 'p1', time_range: {}, bindings: {}, snapshots: {}, started_by: web, started_at: '2026-11-03T08:00:00Z' }
}

const view = (overrides: Partial<DashboardView> = {}): DashboardView => ({ dashboard: dashboard(), version: v2, ...overrides })

function serveDashboard(overrides: Record<string, unknown> = {}) {
  let runs = 0
  return serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/dashboards/d1': view(),
    'GET /api/dashboards/d1/versions': [v2],
    'GET /api/projects/p1/widgets': [coverage, headline],
    'GET /api/widgets/w0': original,
    'GET /api/widgets/w9': orphan,
    'GET /api/widgets/w1': coverage,
    'POST /api/dashboards/d1/runs': () => json(run(`r${++runs}`), 201),
    'GET /api/llm/models': models(),
    'GET /api/projects/p1/pipelines': [pipeline()],
    ...overrides,
  })
}

const grid = () => screen.findByRole('list', { name: 'Dashboard widgets' })
const layoutOf = (body: unknown) =>
  Object.fromEntries((body as { slots: DashboardSlot[] }).slots.map((item) => [item.name, item.layout]))

// jsdom measures nothing, so the grid is taken as 1200 px wide: columns of 85⅓ px, 16 px
// apart, rows of 80 px. One column further is 101⅓ px, one row 96 px.
const COLUMN = 1200 / 12 - 16 + 16 / 12 + 16
const ROW = 96

async function startEditing() {
  fireEvent.click(await screen.findByRole('button', { name: 'Edit layout' }))
  await grid()
}

const done = () => fireEvent.click(screen.getByRole('button', { name: 'Done' }))

function drag(handle: HTMLElement, dx: number, dy: number) {
  fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 500, clientY: 300 })
  fireEvent.pointerMove(handle, { pointerId: 1, clientX: 500 + dx, clientY: 300 + dy })
  fireEvent.pointerUp(handle, { pointerId: 1, clientX: 500 + dx, clientY: 300 + dy })
}

test('dragging a slot moves it and the others make room; Done saves the layout as one new version', async () => {
  const saved: unknown[] = []
  serveDashboard({
    'PUT /api/dashboards/d1/slots': (body: unknown) => {
      saved.push(body)
      const slots = (body as { slots: DashboardSlot[] }).slots
      return view({ dashboard: dashboard({ revision: 4, current_version_id: 'v3' }), version: { ...v2, id: 'v3', number: 3, slots } })
    },
  })
  renderAt('/projects/p1/dashboards/d1')
  await startEditing()

  drag(screen.getByRole('button', { name: 'Move headline' }), -6 * COLUMN, 0)
  // Nothing is saved until Done.
  expect(await screen.findByText(/unsaved layout changes/)).toBeInTheDocument()
  expect(saved).toEqual([])

  done()
  await waitFor(() => expect(saved).toHaveLength(1))
  expect((saved[0] as { expected_revision: number }).expected_revision).toBe(3)
  expect(layoutOf(saved[0])).toEqual({
    coverage: { x: 0, y: 4, w: 6, h: 4 },
    headline: { x: 0, y: 0, w: 6, h: 4 },
    notes: { x: 0, y: 8, w: 12, h: 2 },
  })
  expect(await screen.findByText(/version 3/)).toBeInTheDocument()
})

test('a map keeps its aspect ratio when resized; other widgets resize freely', async () => {
  const saved: unknown[] = []
  serveDashboard({
    'PUT /api/dashboards/d1/slots': (body: unknown) => {
      saved.push(body)
      return view({ version: { ...v2, slots: (body as { slots: DashboardSlot[] }).slots } })
    },
  })
  renderAt('/projects/p1/dashboards/d1')
  await startEditing()

  // The map, three columns wider: it grows taller with it.
  drag(screen.getByRole('button', { name: 'Resize coverage' }), 3 * COLUMN, 0)
  // The number, narrower and lower, as asked; never below its minimum.
  drag(screen.getByRole('button', { name: 'Resize headline' }), -2 * COLUMN, -5 * ROW)
  done()

  // Both changes, in one version.
  await waitFor(() => expect(saved).toHaveLength(1))
  expect(layoutOf(saved[0]).coverage).toEqual({ x: 0, y: 0, w: 9, h: 6 })
  expect(layoutOf(saved[0]).headline).toMatchObject({ w: 4, h: 2 })
})

test('a layout someone else changed meanwhile is not saved: the dashboard is read again, the person told, the changes kept', async () => {
  let reads = 0
  serveDashboard({
    'GET /api/dashboards/d1': () => (reads++, view()),
    'PUT /api/dashboards/d1/slots': json({ detail: 'conflict', expected_revision: 3, revision: 4 }, 409),
  })
  renderAt('/projects/p1/dashboards/d1')
  await startEditing()
  const before = reads

  drag(screen.getByRole('button', { name: 'Move notes' }), 0, ROW)
  done()

  expect(await screen.findByText(/Someone else changed this dashboard/)).toBeInTheDocument()
  await waitFor(() => expect(reads).toBeGreaterThan(before))
  // Still editing, with the move kept, so Done can be pressed again.
  expect(screen.getByRole('button', { name: 'Done' })).toBeInTheDocument()
  expect(screen.getByRole('listitem', { name: 'notes' }).style.getPropertyValue('--row')).toBe('6 / span 2')
})

test('the keyboard moves and resizes too: Enter picks up, arrows move, Enter drops, Escape puts back', async () => {
  const saved: unknown[] = []
  serveDashboard({
    'PUT /api/dashboards/d1/slots': (body: unknown) => {
      saved.push(body)
      return view({ version: { ...v2, slots: (body as { slots: DashboardSlot[] }).slots } })
    },
  })
  renderAt('/projects/p1/dashboards/d1')
  await startEditing()

  const move = screen.getByRole('button', { name: 'Move coverage' })
  act(() => move.focus())
  fireEvent.keyDown(move, { key: 'Enter' })
  expect(move).toHaveAttribute('aria-pressed', 'true')
  expect(screen.getByText(/coverage picked up to move/)).toBeInTheDocument()
  fireEvent.keyDown(move, { key: 'ArrowDown' })
  fireEvent.keyDown(move, { key: 'ArrowDown' })
  expect(screen.getByText('coverage: column 1, row 3, 6 wide, 4 high.')).toBeInTheDocument()
  // Escape: nothing saved, back in place.
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
  done()

  await waitFor(() => expect(saved).toHaveLength(1))
  expect(layoutOf(saved[0]).coverage).toEqual({ x: 1, y: 0, w: 6, h: 4 })
  // An empty slot's minimum is 2 by 2.
  expect(layoutOf(saved[0]).notes).toMatchObject({ w: 11, h: 2 })
})

test('handles appear only while the layout is being edited, and not on an old version', async () => {
  serveDashboard({ 'GET /api/dashboards/d1/versions': [{ ...v2, id: 'v1', number: 1 }, v2] })
  const { router } = renderAt('/projects/p1/dashboards/d1')
  await grid()
  expect(screen.queryByRole('button', { name: 'Move coverage' })).not.toBeInTheDocument()

  await startEditing()
  expect(screen.getByRole('button', { name: 'Move coverage' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Done' }))
  expect(screen.queryByRole('button', { name: 'Move coverage' })).not.toBeInTheDocument()

  await act(() => router.navigate({ to: '.', search: { version: 1 } }))
  expect(await screen.findByText(/You are looking at version 1/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Edit layout' })).not.toBeInTheDocument()
})

// The way back from a copy

test('a pinned copy leads to the session of its original, or says it was not made in one', async () => {
  serveDashboard()
  renderAt('/projects/p1/dashboards/d1')

  const map = await screen.findByRole('article', { name: 'Coverage by region' })
  expect(await within(map).findByRole('link', { name: 'Go to the session it came from' })).toHaveAttribute(
    'href',
    '/projects/p1/sessions/s4?widget=w0',
  )
  const number = screen.getByRole('article', { name: 'Latest coverage' })
  await waitFor(() =>
    expect(within(number).getByRole('button', { name: 'Not made in a session' })).toHaveAttribute('aria-disabled', 'true'),
  )
})

// The agent panel

test('the agent panel opens on the dashboard’s agent session, and closes again', async () => {
  const opened: string[] = []
  serveDashboard({
    'POST /api/dashboards/d1/agent-session': () => {
      opened.push('d1')
      return json(session({ id: 's7', title: 'Screening overview (agent)', origin_dashboard_id: 'd1', panel_dashboard_id: 'd1' }), 201)
    },
    'GET /api/sessions/s7/entries': [entry({ id: 'e1', session_id: 's7', text: 'Earlier question' })],
    'GET /api/sessions/s7/widgets': [],
    'POST /api/projects/p1/runs': json(run('r9'), 201),
  })
  renderAt('/projects/p1/dashboards/d1')
  await grid()
  // Closed at first: looking at a dashboard creates no session.
  expect(screen.queryByRole('complementary', { name: 'Dashboard agent' })).not.toBeInTheDocument()
  expect(opened).toEqual([])

  fireEvent.click(screen.getByRole('button', { name: 'Open the agent panel' }))
  const panel = await screen.findByRole('complementary', { name: 'Dashboard agent' })
  expect(await within(panel).findByText('Earlier question')).toBeInTheDocument()
  expect(within(panel).getByRole('link', { name: 'Open as a session' })).toHaveAttribute('href', '/projects/p1/sessions/s7')
  expect(within(panel).getByRole('form', { name: 'Write a message' })).toBeInTheDocument()
  expect(opened).toEqual(['d1'])

  fireEvent.click(within(panel).getByRole('button', { name: 'Close the agent panel' }))
  expect(screen.queryByRole('complementary', { name: 'Dashboard agent' })).not.toBeInTheDocument()
  // Remembered for the next visit.
  expect(localStorage.getItem('ada-dashboard-agent-panel')).toBe('closed')
})

test('“Add widget” in the header and in an empty slot hand the pipeline, dashboard and slot to the agent panel', async () => {
  const sent: unknown[] = []
  serveDashboard({
    'POST /api/dashboards/d1/agent-session': json(session({ id: 's7' }), 200),
    'GET /api/sessions/s7/entries': [],
    'GET /api/sessions/s7/widgets': [],
    'POST /api/projects/p1/runs': json(run('r9'), 201),
    'POST /api/sessions/s7/messages': (body: unknown) => {
      sent.push(body)
      return json({ entry: entry({ id: 'e9', session_id: 's7' }), turn: turn({ id: 't9', session_id: 's7', status: 'queued' }) }, 201)
    },
    'GET /api/turns/t9': turn({ id: 't9', session_id: 's7', status: 'queued' }),
  })
  renderAt('/projects/p1/dashboards/d1')

  // In an empty slot: that slot.
  const notes = await screen.findByRole('listitem', { name: 'notes' })
  fireEvent.click(within(notes).getByRole('button', { name: 'Add widget' }))
  fireEvent.click(await screen.findByRole('option', { name: /Screening by county/ }))
  const panel = await screen.findByRole('complementary', { name: 'Dashboard agent' })
  const composer = await within(panel).findByRole('form', { name: 'Write a message' })
  expect(within(composer).getByRole('list', { name: 'Context' })).toHaveTextContent(
    'Pipeline: Screening by county → Screening overview, slot “notes”',
  )
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

  // In the header: a new slot.
  const header = screen.getAllByRole('banner').find((element) => element.textContent?.includes('Screening overview'))!
  fireEvent.click(within(header).getByRole('button', { name: 'Add widget' }))
  fireEvent.click(await screen.findByRole('option', { name: /Screening by county/ }))
  expect(await within(composer).findByRole('list', { name: 'Context' })).toHaveTextContent(
    'Pipeline: Screening by county → Screening overview, a new slot',
  )
})

// A widget full size

test('a widget opens full size over the page at its card’s run, and closing goes back where one was', async () => {
  serveDashboard()
  const { router } = renderAt('/projects/p1/dashboards/d1')

  const card = await screen.findByRole('article', { name: 'Coverage by region' })
  await within(card).findByTitle('Widget: Coverage by region')
  const page = screen.getByRole('list', { name: 'Dashboard widgets' })
  fireEvent.click(within(card).getByRole('link', { name: 'Open full size' }))

  await waitFor(() => expect(router.state.location.search).toEqual({ open: 'w1' }))
  const dialog = await screen.findByRole('dialog', { name: 'Coverage by region' })
  // The card's run, not a new one; the page beneath stays as it was.
  expect(await within(dialog).findByTitle('Widget: Coverage by region')).toHaveAttribute(
    'src',
    'http://localhost:5174/map.html#widget=w1&run=r1',
  )
  expect(page).toBeInTheDocument()

  fireEvent.keyDown(dialog, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(router.state.location.search).toEqual({})
  expect(screen.getByRole('list', { name: 'Dashboard widgets' })).toBe(page)

  // The browser's back closes it too.
  fireEvent.click(within(card).getByRole('link', { name: 'Open full size' }))
  await screen.findByRole('dialog', { name: 'Coverage by region' })
  act(() => router.history.back())
  await waitFor(() => expect(router.state.location.search).toEqual({}))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})

test('a link straight to `?open=` shows the widget at a run of its own; closing drops it from the address', async () => {
  let started = 0
  serveDashboard({ 'POST /api/projects/p1/runs': () => json(run(`own${++started}`), 201) })
  const { router } = renderAt('/projects/p1/dashboards/d1?open=w1')

  const dialog = await screen.findByRole('dialog', { name: 'Coverage by region' })
  expect(await within(dialog).findByTitle('Widget: Coverage by region')).toHaveAttribute(
    'src',
    'http://localhost:5174/map.html#widget=w1&run=own1',
  )
  fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(router.state.location.pathname).toBe('/projects/p1/dashboards/d1')
  expect(router.state.location.search).toEqual({})
})

test('unsaved layout changes are discarded on request, and leaving with them asks first', async () => {
  const saved: unknown[] = []
  serveDashboard({ 'PUT /api/dashboards/d1/slots': (body: unknown) => (saved.push(body), view()) })
  const { router } = renderAt('/projects/p1/dashboards/d1')
  await startEditing()

  drag(screen.getByRole('button', { name: 'Move notes' }), 0, ROW)
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  // A blocked navigation never settles, so it is not awaited.
  act(() => void router.navigate({ to: '/projects/$projectId', params: { projectId: 'p1' } }))
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce())
  expect(router.state.location.pathname).toBe('/projects/p1/dashboards/d1')

  fireEvent.click(screen.getByRole('button', { name: 'Discard the layout changes' }))
  expect(screen.getByRole('listitem', { name: 'notes' }).style.getPropertyValue('--row')).toBe('5 / span 2')
  expect(screen.getByRole('button', { name: 'Edit layout' })).toBeInTheDocument()
  act(() => void router.navigate({ to: '/projects/$projectId', params: { projectId: 'p1' } }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/projects/p1'))
  expect(confirm).toHaveBeenCalledOnce()
  expect(saved).toEqual([])
  confirm.mockRestore()
})
