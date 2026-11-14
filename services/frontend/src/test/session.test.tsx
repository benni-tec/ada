import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import { claude, entry, FakeEventSource, json, project, renderAt, serveApi, session, web, widget } from './app'

const external = widget({
  id: 'w2',
  type: 'value',
  title: 'Latest coverage',
  created_by: claude,
  note: 'The headline number for 2024',
  created_at: '2026-11-01T09:20:00Z',
})

const record = [
  entry({ id: 'e1', text: 'Look at screening coverage by region', actor: web }),
  entry({ id: 'e2', kind: 'operator', ref: 'op_1', text: 'Load the coverage table', actor: claude }),
  entry({ id: 'e3', kind: 'widget', ref: 'w1', text: '', actor: web }),
  entry({ id: 'e4', kind: 'widget', ref: 'w2', text: external.note, actor: claude }),
]

/** The runs the page started, in order. */
const started: string[] = []

function run(id: string) {
  return { id, project_id: 'p1', time_range: { start: null, end: null }, bindings: {}, snapshots: {}, started_by: web, started_at: '2026-11-01T09:30:00Z' }
}

function serveSession(overrides: Record<string, unknown> = {}) {
  started.length = 0
  return serveApi({
    'GET /api/projects/p1': project(),
    'POST /api/projects/p1/runs': () => {
      started.push(`r${started.length + 1}`)
      return json(run(started.at(-1)!), 201)
    },
    'GET /api/projects/p1/sources': [],
    'GET /api/operators/op_1/lineage': [],
    'GET /api/sessions/s1': session(),
    'GET /api/sessions/s1/entries': record,
    'GET /api/sessions/s1/widgets': [widget(), external],
    'GET /api/operators/op_1': {
      id: 'op_1',
      project_id: 'p1',
      kind: 'source',
      params: {},
      inputs: [],
      output: { kind: 'table', columns: [{ name: 'a', type: 'text', nullable: true }], roles: {}, derived: false },
      materializing: true,
      created_by: claude,
      created_at: '2026-11-01T09:07:00Z',
    },
    ...overrides,
  })
}

test('shows the record in order, with widgets in frames', async () => {
  serveSession()
  renderAt('/projects/p1/sessions/s1')

  const items = within(await screen.findByRole('list', { name: 'Session record' })).getAllByRole('listitem')
  expect(items).toHaveLength(4)
  expect(items[0]).toHaveTextContent('Look at screening coverage by region')
  expect(await within(items[1]).findByText('Loaded a data source')).toBeInTheDocument()
  expect(items[1]).toHaveTextContent('Load the coverage table')

  const frame = await within(items[2]).findByTitle('Widget: Coverage by region')
  expect(frame).toHaveAttribute('src', 'http://localhost:5174/line-chart.html#widget=w1&run=r1')
  expect(frame).toHaveAttribute('sandbox', 'allow-scripts allow-same-origin')
  // No dashboard in the panel, so no panel.
  expect(screen.queryByRole('complementary', { name: 'Dashboard' })).not.toBeInTheDocument()
})

test('marks a widget made by an external agent with its client and note', async () => {
  serveSession()
  renderAt('/projects/p1/sessions/s1')

  const card = await screen.findByRole('article', { name: 'Latest coverage' })
  const header = within(card).getByRole('banner')
  expect(header).toHaveTextContent('External agent: ↗Claude Desktop')
  expect(header).toHaveTextContent('The headline number for 2024')
  expect(within(header).getByRole('time')).toHaveAttribute('datetime', '2026-11-01T09:20:00Z')

  const own = screen.getByRole('article', { name: 'Coverage by region' })
  expect(own).toHaveTextContent('Person (web)')
  expect(own).not.toHaveTextContent('External agent')
})

test('highlights the widget named in the address', async () => {
  serveSession()
  renderAt('/projects/p1/sessions/s1?widget=w2')

  const card = await screen.findByRole('article', { name: 'Latest coverage' })
  expect(card).toHaveAttribute('data-highlighted', 'true')
  expect(screen.getByRole('article', { name: 'Coverage by region' })).not.toHaveAttribute('data-highlighted')
})

test('shows the dashboard panel when the session has one', async () => {
  serveSession({ 'GET /api/sessions/s1': session({ panel_dashboard_id: 'd1' }) })
  renderAt('/projects/p1/sessions/s1')

  expect(await screen.findByRole('complementary', { name: 'Dashboard' })).toBeInTheDocument()
})

test('adds a message', async () => {
  const sent: unknown[] = []
  serveSession({
    'POST /api/sessions/s1/messages': (body: unknown) => {
      sent.push(body)
      return json({ entry: entry({ id: 'e5', text: 'And mortality?' }), turn: null }, 201)
    },
  })
  renderAt('/projects/p1/sessions/s1')

  fireEvent.change(await screen.findByLabelText('Message'), { target: { value: 'And mortality?' } })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))

  // No models file is known here: the message goes without a model, and no context.
  await waitFor(() => expect(sent).toEqual([{ text: 'And mortality?', context: [] }]))
  await waitFor(() => expect(screen.getByLabelText('Message')).toHaveValue(''))
})

test('shows why a message was not sent', async () => {
  serveSession({ 'POST /api/sessions/s1/messages': json({ detail: 'The session is closed' }, 422) })
  renderAt('/projects/p1/sessions/s1')

  fireEvent.change(await screen.findByLabelText('Message'), { target: { value: 'Hello' } })
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Not sent: The session is closed')
  expect(screen.getByLabelText('Message')).toHaveValue('Hello')
})

test('on a conflict, reads the session again and says what changed', async () => {
  let stored = session()
  const patches: unknown[] = []
  serveSession({
    'GET /api/sessions/s1': () => stored,
    'PATCH /api/sessions/s1': (body: unknown) => {
      patches.push(body)
      const { expected_revision } = body as { expected_revision: number }
      if (expected_revision !== stored.revision) {
        return json(
          { detail: 'conflict', expected_revision, revision: stored.revision },
          409,
        )
      }
      stored = { ...stored, title: (body as { title: string }).title, revision: stored.revision + 1 }
      return stored
    },
  })
  renderAt('/projects/p1/sessions/s1')

  await screen.findByRole('heading', { name: 'Why did coverage drop?', level: 1 })
  // An agent renames the session after the page read it.
  stored = { ...stored, title: 'Coverage in the north', revision: 2 }

  fireEvent.click(screen.getByRole('button', { name: 'Rename' }))
  fireEvent.change(screen.getByLabelText('New session title'), { target: { value: 'Coverage drop 2023' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))

  const notice = await screen.findByRole('alert')
  expect(notice).toHaveTextContent('its title is now “Coverage in the north”')
  expect(notice).toHaveTextContent('Your title was not saved')
  expect(patches).toEqual([{ title: 'Coverage drop 2023', expected_revision: 1 }])
  // The draft is kept, and saving again goes against the revision just read.
  expect(screen.getByLabelText('New session title')).toHaveValue('Coverage drop 2023')

  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('heading', { name: 'Coverage drop 2023', level: 1 })).toBeInTheDocument()
  expect(patches[1]).toEqual({ title: 'Coverage drop 2023', expected_revision: 2 })
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('refetches the record when the live stream says an entry was added', async () => {
  let entries = record.slice(0, 1)
  serveSession({ 'GET /api/sessions/s1/entries': () => entries })
  renderAt('/projects/p1/sessions/s1')

  await screen.findByText('Look at screening coverage by region')
  const stream = FakeEventSource.latest()
  expect(stream.url).toBe('/api/projects/p1/events')
  act(() => stream.open())
  expect(screen.getByRole('status', { name: 'Live updates: Live' })).toBeInTheDocument()

  entries = [...entries, entry({ id: 'e9', text: 'A new message from elsewhere' })]
  act(() =>
    stream.emit('session.entry_added', {
      type: 'session.entry_added',
      project_id: 'p1',
      payload: { session_id: 's1', entry_id: 'e9' },
      at: '2026-11-01T10:00:00Z',
    }),
  )

  expect(await screen.findByText('A new message from elsewhere')).toBeInTheDocument()
})

test('starts one run for the whole page, which every card reads, and a new one when data changes', async () => {
  serveSession()
  renderAt('/projects/p1/sessions/s1')

  expect(await screen.findByTitle('Widget: Coverage by region')).toHaveAttribute(
    'src',
    'http://localhost:5174/line-chart.html#widget=w1&run=r1',
  )
  expect(await screen.findByTitle('Widget: Latest coverage')).toHaveAttribute(
    'src',
    'http://localhost:5174/value.html#widget=w2&run=r1',
  )
  expect(started).toEqual(['r1'])

  // New data: one new run, which both frames then read.
  act(() =>
    FakeEventSource.latest().emit('source.refreshed', {
      type: 'source.refreshed',
      project_id: 'p1',
      payload: { data_source_id: 'ds1', changed: true },
      at: '2026-11-01T10:00:00Z',
    }),
  )
  await waitFor(() => expect(screen.getByTitle('Widget: Coverage by region').getAttribute('src')).toContain('run=r2'))
  expect(screen.getByTitle('Widget: Latest coverage').getAttribute('src')).toContain('run=r2')
  expect(started).toEqual(['r1', 'r2'])
})

test('a card waits for the page’s run instead of starting one of its own', async () => {
  let answer: (response: Response) => void = () => {}
  serveSession({ 'POST /api/projects/p1/runs': () => new Promise<Response>((resolve) => (answer = resolve)) })
  renderAt('/projects/p1/sessions/s1')

  const card = await screen.findByRole('article', { name: 'Coverage by region' })
  expect(within(card).getByText('Starting the page’s run…')).toBeInTheDocument()
  expect(within(card).queryByTitle('Widget: Coverage by region')).not.toBeInTheDocument()

  act(() => answer(json(run('r7'), 201)))
  expect(await within(card).findByTitle('Widget: Coverage by region')).toHaveAttribute(
    'src',
    'http://localhost:5174/line-chart.html#widget=w1&run=r7',
  )
})
