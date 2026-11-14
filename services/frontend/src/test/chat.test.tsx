import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import type { AgentTurn, Part } from '@/lib/api'

import { emit, entry, FakeEventSource, json, models, pipeline, project, renderAt, serveApi, session, turn, web } from './app'

// The session's chat: the composer, the agent's turns drawn with Trace, streaming.

const question = entry({ id: 'e1', text: 'How did participation change?', actor: web })
const answerEntry = entry({ id: 'e2', kind: 'agent_turn', ref: 't1', actor: { kind: 'agent', name: 'gemini/flash' } })

function run(id: string) {
  return { id, project_id: 'p1', time_range: {}, bindings: {}, snapshots: {}, started_by: web, started_at: '2026-11-01T09:30:00Z' }
}

function serveChat(overrides: Record<string, unknown> = {}) {
  return serveApi({
    'GET /api/projects/p1': project(),
    'POST /api/projects/p1/runs': json(run('r1'), 201),
    'GET /api/sessions/s1': session(),
    'GET /api/sessions/s1/entries': [question, answerEntry],
    'GET /api/sessions/s1/widgets': [],
    'GET /api/turns/t1': turn({ status: 'done', parts: [{ type: 'text', text: 'It rose.' }] }),
    'GET /api/llm/models': models(),
    'GET /api/projects/p1/pipelines': [pipeline(), pipeline({ operator_id: 'op_p2', name: 'Lung cancer survival', sources: [{ data_source_id: 'ds2', name: 'NORDCAN' }] })],
    ...overrides,
  })
}

const record = () => screen.findByRole('list', { name: 'Session record' })
const composer = () => screen.getByRole('form', { name: 'Write a message' })

test('the record reads as a conversation: the question, then the agent’s answer', async () => {
  serveChat()
  renderAt('/projects/p1/sessions/s1')

  const items = within(await record()).getAllByRole('listitem')
  expect(items[0]).toHaveTextContent('How did participation change?')
  expect(items[0].querySelector('[data-slot="message"]')).toHaveAttribute('data-align', 'end')
  expect(await within(items[1]).findByText('It rose.')).toBeInTheDocument()
  expect(items[1]).toHaveTextContent('Platform agent (gemini/flash)')
  expect(items[1].querySelector('[data-slot="message"]')).toHaveAttribute('data-align', 'start')
})

test('each kind of part is drawn with Trace: reasoning, tool calls with input and output, sources, text', async () => {
  const parts: Part[] = [
    { type: 'reasoning', text: 'The question is about the latest year.' },
    {
      type: 'tool',
      tool_call_id: 'c1',
      tool_name: 'run_sql',
      state: 'output-available',
      input: { sql: 'SELECT 1' },
      output: { rows: 1 },
      error_text: null,
    },
    {
      type: 'tool',
      tool_call_id: 'c2',
      tool_name: 'create_widget',
      state: 'output-error',
      input: { type: 'map' },
      output: null,
      error_text: 'No geography role',
    },
    { type: 'source', source_id: 'ds1', title: 'Sotkanet screening', url: 'https://sotkanet.test/3621' },
    { type: 'source', source_id: 'ds2', title: 'Wellbeing counties', url: null },
    { type: 'text', text: 'Participation rose in 2024.' },
  ]
  serveChat({ 'GET /api/turns/t1': turn({ status: 'done', parts }) })
  renderAt('/projects/p1/sessions/s1')

  const answer = within(await record()).getAllByRole('listitem')[1]
  const steps = await within(answer).findByLabelText('Steps')
  expect(steps).toHaveAttribute('data-slot', 'trace')
  const lines = [...steps.querySelectorAll(':scope > * [data-slot="trace-line"], :scope > [data-slot="trace-line"]')]
  expect(lines.map((line) => line.textContent)).toEqual([
    'Thought',
    'Called run_sql',
    'Failed: create_widget',
    'Used 2 sources',
  ])
  expect(lines[2]).toHaveAttribute('data-status', 'error')

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
  expect(within(answer).getByText('Participation rose in 2024.')).toHaveAttribute('data-part', 'text')
})

test('sends a message with its context chips and the picked model; Enter sends, Shift+Enter does not', async () => {
  const sent: unknown[] = []
  serveChat({
    'POST /api/sessions/s1/messages': (body: unknown) => {
      sent.push(body)
      return json({ entry: entry({ id: 'e3', text: 'Map it' }), turn: turn({ id: 't2', status: 'queued' }) }, 201)
    },
    'GET /api/turns/t2': turn({ id: 't2', status: 'queued' }),
  })
  renderAt('/projects/p1/sessions/s1')
  await record()

  // Add widget: the pipeline goes on the message as a chip.
  fireEvent.click(within(composer()).getByRole('button', { name: 'Add widget' }))
  const search = await screen.findByRole('combobox', { name: 'Search the pipelines' })
  fireEvent.change(search, { target: { value: 'nordcan' } })
  const options = await screen.findAllByRole('option')
  expect(options).toHaveLength(1)
  expect(options[0]).toHaveTextContent('Lung cancer survival')
  fireEvent.change(search, { target: { value: '' } })
  fireEvent.click(await screen.findByRole('option', { name: /Screening by county/ }))
  const chips = await within(composer()).findByRole('list', { name: 'Context' })
  expect(chips).toHaveTextContent('Pipeline: Screening by county')

  // A model other than the default; one without its key is there, but disabled.
  const picker = await within(composer()).findByRole('button', { name: 'Model: gemini/flash' })
  fireEvent.pointerDown(picker, { button: 0, ctrlKey: false })
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

  await waitFor(() =>
    expect(sent).toEqual([{ text: 'Map it', context: [{ kind: 'pipeline', operator_id: 'op_p1' }], model: 'gemini/pro' }]),
  )
  await waitFor(() => expect(input).toHaveValue(''))
  expect(within(composer()).queryByRole('list', { name: 'Context' })).not.toBeInTheDocument()
})

test('a chip can be taken off before sending', async () => {
  serveChat()
  renderAt('/projects/p1/sessions/s1')
  await record()

  fireEvent.click(within(composer()).getByRole('button', { name: 'Add widget' }))
  fireEvent.click(await screen.findByRole('option', { name: /Screening by county/ }))
  fireEvent.click(await within(composer()).findByRole('button', { name: 'Remove Pipeline: Screening by county' }))
  expect(within(composer()).queryByRole('list', { name: 'Context' })).not.toBeInTheDocument()
})

test('without an agent the message is still recorded, and the composer says nobody will answer', async () => {
  const sent: unknown[] = []
  serveChat({
    'GET /api/sessions/s1/entries': [],
    'GET /api/llm/models': models({ models: [], session_agent: null }),
    'POST /api/sessions/s1/messages': (body: unknown) => {
      sent.push(body)
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
  await waitFor(() => expect(sent).toEqual([{ text: 'A note', context: [] }]))
})

test('the answer streams in by index: a part replaces the one at its index', async () => {
  let stored = turn({ status: 'running', parts: [] })
  serveChat({ 'GET /api/turns/t1': () => stored })
  renderAt('/projects/p1/sessions/s1')
  const answer = within(await record()).getAllByRole('listitem')[1]
  expect(await within(answer).findByText('Thinking')).toBeInTheDocument()

  const part = (index: number, value: Part) => act(() => emit('agent.turn_part', { session_id: 's1', turn_id: 't1', index, part: value }))
  part(0, { type: 'reasoning', text: 'Look at' })
  part(0, { type: 'reasoning', text: 'Look at the latest year' })
  part(1, { type: 'tool', tool_call_id: 'c1', tool_name: 'run_sql', state: 'input-available', input: {}, output: null, error_text: null })
  expect(await within(answer).findByText('Calling run_sql')).toBeInTheDocument()
  part(1, { type: 'tool', tool_call_id: 'c1', tool_name: 'run_sql', state: 'output-available', input: {}, output: 1, error_text: null })
  part(2, { type: 'text', text: 'It' })
  part(2, { type: 'text', text: 'It rose by two points.' })

  expect(await within(answer).findByText('It rose by two points.')).toBeInTheDocument()
  expect(within(answer).queryByText('It')).not.toBeInTheDocument()
  expect(within(answer).getByText('Called run_sql')).toBeInTheDocument()
  expect(within(answer).getAllByText('Thought')).toHaveLength(1)

  // Finished: the stored turn is read again.
  stored = turn({ status: 'done', parts: [{ type: 'text', text: 'It rose by two points, from 78 to 80 %.' }] })
  act(() => emit('agent.turn_finished', { session_id: 's1', turn_id: 't1', status: 'done' }))
  expect(await within(answer).findByText('It rose by two points, from 78 to 80 %.')).toBeInTheDocument()
})

test('a part that arrives while the turn is read again is kept, and after a reconnect the turn is read again', async () => {
  let reads = 0
  let stored: AgentTurn = turn({ status: 'running', parts: [{ type: 'text', text: 'One' }] })
  serveChat({ 'GET /api/turns/t1': () => (reads++, stored) })
  renderAt('/projects/p1/sessions/s1')
  const answer = within(await record()).getAllByRole('listitem')[1]
  expect(await within(answer).findByText('One')).toBeInTheDocument()
  const stream = FakeEventSource.latest()
  act(() => stream.open())

  // The stored turn lags behind the stream: a refetch must not drop the newer part.
  act(() => emit('agent.turn_part', { session_id: 's1', turn_id: 't1', index: 1, part: { type: 'reasoning', text: 'More' } }))
  act(() => emit('agent.turn_started', { session_id: 's1', turn_id: 't1' }))
  await waitFor(() => expect(reads).toBe(2))
  expect(await within(answer).findByText('Thinking')).toBeInTheDocument()

  // The connection drops; meanwhile the turn went on. On reconnect it is read again and
  // the stream continues from there.
  stored = turn({ status: 'running', parts: [{ type: 'text', text: 'One' }, { type: 'reasoning', text: 'More' }, { type: 'text', text: 'Two' }] })
  act(() => stream.fail())
  await waitFor(() => expect(FakeEventSource.instances.length).toBe(2), { timeout: 4000 })
  act(() => FakeEventSource.latest().open())
  expect(await within(answer).findByText('Two')).toBeInTheDocument()
  expect(reads).toBe(3)
  act(() => emit('agent.turn_part', { session_id: 's1', turn_id: 't1', index: 3, part: { type: 'text', text: 'Three' } }))
  expect(await within(answer).findByText('Three')).toBeInTheDocument()
})

test('while the agent answers, a stop button asks it to stop', async () => {
  const cancelled: string[] = []
  let stored = turn({ status: 'running', parts: [{ type: 'reasoning', text: 'Hmm' }] })
  serveChat({
    'GET /api/turns/t1': () => stored,
    'POST /api/turns/t1/cancel': () => {
      cancelled.push('t1')
      stored = turn({ status: 'cancelled', parts: stored.parts })
      return json({}, 202)
    },
  })
  renderAt('/projects/p1/sessions/s1')
  await record()

  fireEvent.click(await within(composer()).findByRole('button', { name: 'Stop the agent' }))
  await waitFor(() => expect(cancelled).toEqual(['t1']))
  expect(await screen.findByText('Stopped')).toBeInTheDocument()
  expect(within(composer()).queryByRole('button', { name: 'Stop the agent' })).not.toBeInTheDocument()
})

test('a failed turn says why', async () => {
  serveChat({ 'GET /api/turns/t1': turn({ status: 'failed', error: 'The model is overloaded' }) })
  renderAt('/projects/p1/sessions/s1')

  const answer = within(await record()).getAllByRole('listitem')[1]
  expect(await within(answer).findByRole('alert')).toHaveTextContent('The agent failed: The model is overloaded')
})

test('a message’s context is shown with it, named from what it points at', async () => {
  serveChat({
    'GET /api/sessions/s1/entries': [
      entry({
        id: 'e1',
        text: 'Show this',
        context: [
          { kind: 'pipeline', operator_id: 'op_p1' },
          { kind: 'dashboard', dashboard_id: 'd1', slot: 'top' },
        ],
      }),
    ],
    'GET /api/dashboards/d1': { dashboard: { id: 'd1', name: 'Screening overview' }, version: null },
  })
  renderAt('/projects/p1/sessions/s1')

  const message = within(await record()).getAllByRole('listitem')[0]
  const context = within(message).getByRole('list', { name: 'Context' })
  expect(await within(context).findByText('Pipeline: Screening by county')).toBeInTheDocument()
  expect(await within(context).findByText('Dashboard: Screening overview, slot “top”')).toBeInTheDocument()
})
