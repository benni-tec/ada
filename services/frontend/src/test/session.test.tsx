import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import type { AgentTurn, Part } from '@/lib/api'

import {
  claude,
  dashboard,
  emit,
  entry,
  FakeEventSource,
  json,
  models,
  pipeline,
  project,
  renderAt,
  run,
  serveApi,
  session,
  turn,
  web,
  widget,
} from './app'

// A session: its record as a chat with widget cards at one run of the page, the composer,
// the agent's turns drawn with Trace and streamed in, and pinning a widget to a dashboard.

const external = widget({
  id: 'w2',
  type: 'value',
  title: 'Latest coverage',
  created_by: claude,
  note: 'The headline number for 2024',
  created_at: '2026-11-01T09:20:00Z',
})

const question = entry({ id: 'e1', text: 'How did participation change?', actor: web })
const answer = entry({ id: 'e2', kind: 'agent_turn', ref: 't1', actor: { kind: 'agent', name: 'gemini/flash' } })
const record = [
  question,
  answer,
  entry({ id: 'e3', kind: 'operator', ref: 'op_1', text: 'Load the coverage table', actor: claude }),
  entry({ id: 'e4', kind: 'widget', ref: 'w1', actor: web }),
  entry({ id: 'e5', kind: 'widget', ref: 'w2', text: external.note, actor: claude }),
]

/** The runs the page started, in order. */
const started: string[] = []

function serveSession(overrides: Record<string, unknown> = {}) {
  started.length = 0
  return serveApi({
    'GET /api/projects/p1': project(),
    'POST /api/projects/p1/runs': () => {
      started.push(`r${started.length + 1}`)
      return json(run(started.at(-1)!), 201)
    },
    'GET /api/projects/p1/sources': [],
    'GET /api/sessions/s1': session(),
    'GET /api/sessions/s1/entries': record,
    'GET /api/sessions/s1/widgets': [widget(), external],
    'GET /api/operators/op_1': {
      id: 'op_1',
      project_id: 'p1',
      kind: 'source',
      params: {},
      inputs: [],
      output: { kind: 'table', columns: [], roles: {}, derived: false },
      materializing: true,
      created_by: claude,
      created_at: '2026-11-01T09:07:00Z',
    },
    'GET /api/turns/t1': turn({ status: 'done', parts: [{ type: 'text', text: 'It rose.' }] }),
    'GET /api/llm/models': models(),
    'GET /api/projects/p1/pipelines': [
      pipeline(),
      pipeline({ operator_id: 'op_p2', name: 'Lung cancer survival', sources: [{ data_source_id: 'ds2', name: 'NORDCAN' }] }),
    ],
    ...overrides,
  })
}

const items = async () => within(await screen.findByRole('list', { name: 'Session record' })).getAllByRole('listitem')
const composer = () => screen.getByRole('form', { name: 'Write a message' })

test('the record reads as a conversation, its widget cards all at the page’s one run', async () => {
  // The page's run is slow to start: the cards wait for it instead of starting their own.
  let startRun = () => {}
  let entries = record
  serveSession({
    'GET /api/sessions/s1/entries': () => entries,
    'POST /api/projects/p1/runs': () => {
      started.push(`r${started.length + 1}`)
      const response = json(run(started.at(-1)!), 201)
      return started.length === 1 ? new Promise<Response>((resolve) => (startRun = () => resolve(response))) : response
    },
  })
  renderAt('/projects/p1/sessions/s1?widget=w2')

  const [message, reply, operator, own, made] = await items()
  // The person's message on the right, the agent's answer on the left.
  expect(message).toHaveTextContent('How did participation change?')
  expect(message.querySelector('[data-slot="message"]')).toHaveAttribute('data-align', 'end')
  expect(await within(reply).findByText('It rose.')).toBeInTheDocument()
  expect(reply).toHaveTextContent('Platform agent (gemini/flash)')
  expect(await within(operator).findByText('Loaded a data source')).toBeInTheDocument()
  expect(operator).toHaveTextContent('Load the coverage table')

  expect(within(own).getByText('Starting the page’s run…')).toBeInTheDocument()
  act(() => startRun())
  const frame = await within(own).findByTitle('Widget: Coverage by region')
  expect(frame).toHaveAttribute('src', 'http://localhost:5174/line-chart.html#widget=w1&run=r1')
  expect(frame).toHaveAttribute('sandbox', 'allow-scripts allow-same-origin')
  expect(await within(made).findByTitle('Widget: Latest coverage')).toHaveAttribute('src', 'http://localhost:5174/value.html#widget=w2&run=r1')
  expect(started).toEqual(['r1'])

  // A widget made by an external agent names its client and note; `?widget=` marks one.
  const card = screen.getByRole('article', { name: 'Latest coverage' })
  expect(within(card).getByRole('banner')).toHaveTextContent('External agent: ↗Claude Desktop')
  expect(within(card).getByRole('banner')).toHaveTextContent('The headline number for 2024')
  expect(card).toHaveAttribute('data-highlighted', 'true')
  expect(screen.getByRole('article', { name: 'Coverage by region' })).not.toHaveAttribute('data-highlighted')
  // No dashboard beside it.
  expect(screen.queryByRole('complementary', { name: 'Dashboard' })).not.toBeInTheDocument()

  // The live stream: a new entry is read, new data starts one new run for every card.
  const stream = FakeEventSource.latest()
  expect(stream.url).toBe('/api/projects/p1/events')
  act(() => stream.open())
  expect(screen.getByRole('status', { name: 'Live updates: Live' })).toBeInTheDocument()
  entries = [...record, entry({ id: 'e9', text: 'A new message from elsewhere' })]
  act(() => emit('session.entry_added', { session_id: 's1', entry_id: 'e9' }))
  expect(await screen.findByText('A new message from elsewhere')).toBeInTheDocument()
  act(() => emit('source.refreshed', { data_source_id: 'ds1', changed: true }))
  await waitFor(() => expect(screen.getByTitle('Widget: Coverage by region').getAttribute('src')).toContain('run=r2'))
  expect(screen.getByTitle('Widget: Latest coverage').getAttribute('src')).toContain('run=r2')
  expect(started).toEqual(['r1', 'r2'])
})

test('an agent turn is drawn with Trace: reasoning, tool calls with input and output, sources, text; a failed one says why', async () => {
  const parts: Part[] = [
    { type: 'reasoning', text: 'The question is about the latest year.' },
    { type: 'tool', tool_call_id: 'c1', tool_name: 'run_sql', state: 'output-available', input: { sql: 'SELECT 1' }, output: { rows: 1 }, error_text: null },
    { type: 'tool', tool_call_id: 'c2', tool_name: 'create_widget', state: 'output-error', input: { type: 'map' }, output: null, error_text: 'No geography role' },
    { type: 'source', source_id: 'ds1', title: 'Sotkanet screening', url: 'https://sotkanet.test/3621' },
    { type: 'source', source_id: 'ds2', title: 'Wellbeing counties', url: null },
    { type: 'text', text: 'Participation rose in 2024.' },
  ]
  serveSession({
    'GET /api/sessions/s1/entries': [question, answer, entry({ id: 'e3', kind: 'agent_turn', ref: 't2', actor: answer.actor })],
    'GET /api/turns/t1': turn({ status: 'done', parts }),
    'GET /api/turns/t2': turn({ id: 't2', status: 'failed', error: 'The model is overloaded' }),
  })
  renderAt('/projects/p1/sessions/s1')

  const [, reply, failed] = await items()
  const steps = await within(reply).findByLabelText('Steps')
  const lines = [...steps.querySelectorAll('[data-slot="trace-line"]')]
  expect(lines.map((line) => line.textContent)).toEqual(['Thought', 'Called run_sql', 'Failed: create_widget', 'Used 2 sources'])

  // Each opens to what it holds.
  fireEvent.click(within(steps).getByRole('button', { name: 'Thought' }))
  expect(within(steps).getByText('The question is about the latest year.')).toBeVisible()
  fireEvent.click(within(steps).getByRole('button', { name: /Called run_sql/ }))
  expect(within(steps).getByRole('figure', { name: 'Input' })).toHaveTextContent('"sql": "SELECT 1"')
  expect(within(steps).getByRole('figure', { name: 'Output' })).toHaveTextContent('"rows": 1')
  fireEvent.click(within(steps).getByRole('button', { name: /Failed: create_widget/ }))
  expect(within(steps).getByRole('figure', { name: 'Error' })).toHaveTextContent('No geography role')
  fireEvent.click(within(steps).getByRole('button', { name: 'Used 2 sources' }))
  expect(within(steps).getByRole('link', { name: /Sotkanet screening/ })).toHaveAttribute('href', 'https://sotkanet.test/3621')
  expect(within(steps).getByText('Wellbeing counties')).toBeInTheDocument()
  // The text is the answer itself, after the steps.
  expect(within(reply).getByText('Participation rose in 2024.')).toHaveAttribute('data-part', 'text')

  expect(await within(failed).findByRole('alert')).toHaveTextContent('The agent failed: The model is overloaded')
})

test('a message goes with its context chips and the picked model; Enter sends, Shift+Enter does not', async () => {
  const sent: unknown[] = []
  const mapIt = entry({
    id: 'e9',
    text: 'Map it',
    context: [
      { kind: 'pipeline', operator_id: 'op_p1' },
      { kind: 'dashboard', dashboard_id: 'd1', slot: 'top' },
    ],
  })
  serveSession({
    'GET /api/sessions/s1/entries': () => [question, answer, ...(sent.length ? [mapIt] : [])],
    'POST /api/sessions/s1/messages': (body: unknown) => {
      sent.push(body)
      return json({ entry: mapIt, turn: turn({ id: 't2', status: 'queued' }) }, 201)
    },
    'GET /api/turns/t2': turn({ id: 't2', status: 'queued' }),
    'GET /api/dashboards/d1': { dashboard: dashboard(), version: null },
  })
  renderAt('/projects/p1/sessions/s1')
  await items()

  // Add widget: the pipelines are searched by their sources too; a chip can be taken off.
  fireEvent.click(within(composer()).getByRole('button', { name: 'Add widget' }))
  const search = await screen.findByRole('combobox', { name: 'Search the pipelines' })
  fireEvent.change(search, { target: { value: 'nordcan' } })
  expect((await screen.findAllByRole('option')).map((option) => option.textContent)).toEqual([expect.stringContaining('Lung cancer survival')])
  fireEvent.change(search, { target: { value: '' } })
  fireEvent.click(await screen.findByRole('option', { name: /Screening by county/ }))
  fireEvent.click(await within(composer()).findByRole('button', { name: 'Remove Pipeline: Screening by county' }))
  expect(within(composer()).queryByRole('list', { name: 'Context' })).not.toBeInTheDocument()
  fireEvent.click(within(composer()).getByRole('button', { name: 'Add widget' }))
  fireEvent.click(await screen.findByRole('option', { name: /Screening by county/ }))
  expect(await within(composer()).findByRole('list', { name: 'Context' })).toHaveTextContent('Pipeline: Screening by county')

  // A model other than the default; one without its key is there, but disabled.
  fireEvent.pointerDown(await within(composer()).findByRole('button', { name: 'Model: gemini/flash' }), { button: 0, ctrlKey: false })
  const unavailable = await screen.findByRole('menuitemradio', { name: /mistral\/large/ })
  expect(unavailable).toHaveAttribute('aria-disabled', 'true')
  expect(unavailable).toHaveTextContent('MISTRAL_API_KEY is not set')
  fireEvent.click(screen.getByRole('menuitemradio', { name: /gemini\/pro/ }))
  expect(await within(composer()).findByRole('button', { name: 'Model: gemini/pro' })).toBeInTheDocument()

  const input = within(composer()).getByLabelText('Message')
  fireEvent.change(input, { target: { value: 'Map it' } })
  fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })
  expect(sent).toEqual([])
  fireEvent.keyDown(input, { key: 'Enter' })
  await waitFor(() => expect(sent).toEqual([{ text: 'Map it', context: [{ kind: 'pipeline', operator_id: 'op_p1' }], model: 'gemini/pro' }]))
  await waitFor(() => expect(input).toHaveValue(''))
  expect(within(composer()).queryByRole('list', { name: 'Context' })).not.toBeInTheDocument()

  // The recorded message shows its context, named from what it points at.
  const context = within((await items())[2]).getByRole('list', { name: 'Context' })
  expect(await within(context).findByText('Pipeline: Screening by county')).toBeInTheDocument()
  expect(await within(context).findByText('Dashboard: Screening overview, slot “top”')).toBeInTheDocument()
})

test('the answer streams in by index, survives a refetch that lags behind and a reconnect, and can be stopped', async () => {
  let reads = 0
  let stored: AgentTurn = turn({ status: 'running', parts: [] })
  const cancelled: string[] = []
  serveSession({
    'GET /api/sessions/s1/entries': [question, answer],
    'GET /api/turns/t1': () => (reads++, stored),
    'POST /api/turns/t1/cancel': () => {
      cancelled.push('t1')
      stored = { ...stored, status: 'cancelled' }
      return json({}, 202)
    },
  })
  renderAt('/projects/p1/sessions/s1')
  const reply = (await items())[1]
  expect(await within(reply).findByText('Thinking')).toBeInTheDocument()
  const stream = FakeEventSource.latest()
  act(() => stream.open())

  // A part replaces the one at its index.
  const part = (index: number, value: Part) => act(() => emit('agent.turn_part', { session_id: 's1', turn_id: 't1', index, part: value }))
  part(0, { type: 'reasoning', text: 'Look at' })
  part(0, { type: 'reasoning', text: 'Look at the latest year' })
  part(1, { type: 'tool', tool_call_id: 'c1', tool_name: 'run_sql', state: 'input-available', input: {}, output: null, error_text: null })
  expect(await within(reply).findByText('Calling run_sql')).toBeInTheDocument()
  part(1, { type: 'tool', tool_call_id: 'c1', tool_name: 'run_sql', state: 'output-available', input: {}, output: 1, error_text: null })
  part(2, { type: 'text', text: 'It' })
  part(2, { type: 'text', text: 'It rose by two points.' })
  expect(await within(reply).findByText('It rose by two points.')).toBeInTheDocument()
  expect(within(reply).queryByText('It')).not.toBeInTheDocument()
  expect(within(reply).getByText('Called run_sql')).toBeInTheDocument()

  // The stored turn lags behind the stream: a refetch must not drop the newer parts.
  act(() => emit('agent.turn_started', { session_id: 's1', turn_id: 't1' }))
  await waitFor(() => expect(reads).toBe(2))
  expect(within(reply).getByText('It rose by two points.')).toBeInTheDocument()

  // The connection drops; meanwhile the turn went on. On reconnect it is read again.
  stored = turn({ status: 'running', parts: [{ type: 'text', text: 'One' }, { type: 'reasoning', text: 'More' }, { type: 'text', text: 'Two' }] })
  act(() => stream.fail())
  await waitFor(() => expect(FakeEventSource.instances.length).toBe(2))
  act(() => FakeEventSource.latest().open())
  expect(await within(reply).findByText('Two')).toBeInTheDocument()
  expect(reads).toBe(3)
  act(() => emit('agent.turn_part', { session_id: 's1', turn_id: 't1', index: 3, part: { type: 'text', text: 'Three' } }))
  expect(await within(reply).findByText('Three')).toBeInTheDocument()

  // While it runs, a stop button asks it to stop.
  fireEvent.click(within(composer()).getByRole('button', { name: 'Stop the agent' }))
  await waitFor(() => expect(cancelled).toEqual(['t1']))
  expect(await within(reply).findByText('Stopped')).toBeInTheDocument()
  expect(within(composer()).queryByRole('button', { name: 'Stop the agent' })).not.toBeInTheDocument()
})

test('without an agent a message is still recorded and the composer says nobody will answer; a refused one keeps the draft', async () => {
  const sent: unknown[] = []
  serveSession({
    'GET /api/sessions/s1/entries': [],
    'GET /api/llm/models': models({ models: [], session_agent: null }),
    'POST /api/sessions/s1/messages': (body: unknown) => {
      sent.push(body)
      if (sent.length === 1) return json({ detail: 'The session is closed' }, 422)
      return json({ entry: entry({ id: 'e3', text: 'A note' }), turn: null }, 201)
    },
  })
  renderAt('/projects/p1/sessions/s1')

  const note = await within(await screen.findByRole('form', { name: 'Write a message' })).findByRole('note')
  expect(note).toHaveTextContent('No agent is configured, so nobody will answer here')
  expect(within(note).getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '/projects/p1/settings')
  expect(within(composer()).queryByRole('button', { name: /^Model:/ })).not.toBeInTheDocument()
  const input = within(composer()).getByLabelText('Message')
  expect(input).toHaveAccessibleDescription(/No agent is configured/)

  fireEvent.change(input, { target: { value: 'A note' } })
  fireEvent.click(within(composer()).getByRole('button', { name: 'Send' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Not sent: The session is closed')
  expect(input).toHaveValue('A note')

  fireEvent.click(within(composer()).getByRole('button', { name: 'Send' }))
  await waitFor(() => expect(input).toHaveValue(''))
  // No models are known: the message goes without one.
  expect(sent).toEqual([
    { text: 'A note', context: [] },
    { text: 'A note', context: [] },
  ])
})

test('rename: Escape cancels; on a conflict the session is read again and the person told what changed', async () => {
  let stored = session()
  const patches: unknown[] = []
  serveSession({
    'GET /api/sessions/s1': () => stored,
    'PATCH /api/sessions/s1': (body: unknown) => {
      patches.push(body)
      const { expected_revision } = body as { expected_revision: number }
      if (expected_revision !== stored.revision) return json({ detail: 'conflict', expected_revision, revision: stored.revision }, 409)
      stored = { ...stored, title: (body as { title: string }).title, revision: stored.revision + 1 }
      return stored
    },
  })
  renderAt('/projects/p1/sessions/s1')
  await screen.findByRole('heading', { name: 'Why did coverage drop?', level: 1 })

  // The pencil's name is its tooltip.
  const pencil = screen.getByRole('button', { name: 'Rename' })
  act(() => pencil.focus())
  expect(await screen.findByRole('tooltip')).toHaveTextContent('Rename')
  fireEvent.click(pencil)
  fireEvent.change(screen.getByLabelText('New session title'), { target: { value: 'Abandoned' } })
  fireEvent.keyDown(screen.getByLabelText('New session title'), { key: 'Escape' })
  expect(screen.queryByLabelText('New session title')).not.toBeInTheDocument()

  // An agent renames the session after the page read it.
  stored = { ...stored, title: 'Coverage in the north', revision: 2 }
  fireEvent.click(screen.getByRole('button', { name: 'Rename' }))
  fireEvent.change(screen.getByLabelText('New session title'), { target: { value: 'Coverage drop 2023' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))

  const notice = await screen.findByRole('alert')
  expect(notice).toHaveTextContent('its title is now “Coverage in the north”')
  expect(notice).toHaveTextContent('Your title was not saved')
  // The draft is kept, and saving again goes against the revision just read.
  expect(screen.getByLabelText('New session title')).toHaveValue('Coverage drop 2023')
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('heading', { name: 'Coverage drop 2023', level: 1 })).toBeInTheDocument()
  expect(patches).toEqual([
    { title: 'Coverage drop 2023', expected_revision: 1 },
    { title: 'Coverage drop 2023', expected_revision: 2 },
  ])
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('a widget is pinned to a dashboard as a copy, on the dashboard’s latest revision', async () => {
  let pinned: unknown
  serveSession({
    'GET /api/projects/p1/dashboards': [dashboard(), dashboard({ id: 'd2', name: 'Other' })],
    'GET /api/dashboards/d1': { dashboard: dashboard({ revision: 7 }), version: null },
    'POST /api/dashboards/d1/pins': (body: unknown) => {
      pinned = body
      return json({ dashboard: dashboard({ revision: 8 }), version: null }, 201)
    },
  })
  renderAt('/projects/p1/sessions/s1')

  const card = await screen.findByRole('article', { name: 'Coverage by region' })
  fireEvent.click(within(card).getByRole('button', { name: 'Add to dashboard' }))
  const form = await within(card).findByRole('form', { name: 'Pin Coverage by region to a dashboard' })
  await waitFor(() => expect(within(form).getByLabelText('Dashboard')).not.toBeDisabled())
  fireEvent.change(within(form).getByLabelText('Slot name'), { target: { value: 'coverage' } })
  fireEvent.click(within(form).getByRole('button', { name: 'Pin' }))

  const done = await within(card).findByRole('status')
  expect(done).toHaveTextContent('A copy is pinned to Screening overview')
  expect(within(done).getByRole('link', { name: 'Screening overview' })).toHaveAttribute('href', '/projects/p1/dashboards/d1')
  expect(pinned).toEqual({ widget_id: 'w1', slot: 'coverage', expected_revision: 7 })
})
