// DEVELOPMENT ONLY: a stand-in for the wave 3 agent routes, so the chat, the Trace and
// "Add widget" can be looked at against a backend that does not have them yet. It never
// reaches a production build: main.tsx imports it only under `import.meta.env.DEV`, and
// only when switched on with `?mock-agent=1` (off again with `?mock-agent=0`).
//
// Everything it answers lives in memory: messages, turns and dashboard agent sessions are
// never written to the backend. Every other request goes through unchanged. Its turns
// stream like the real ones, as `agent.turn_part` events on the page's live stream.

import type { AgentTurn, Context, LlmModels, Part, Pipeline, Session, SessionEntry } from '@/lib/api'

const flag = 'ada-mock-agent'

export function mockAgentWanted(): boolean {
  const asked = new URLSearchParams(window.location.search).get('mock-agent')
  try {
    if (asked === '1') sessionStorage.setItem(flag, '1')
    if (asked === '0') sessionStorage.removeItem(flag)
    return sessionStorage.getItem(flag) === '1'
  } catch {
    return asked === '1'
  }
}

const models: LlmModels = {
  models: [
    { id: 'mock/fast', provider: 'mock', model: 'fast', purposes: ['session_agent'], available: true, reason: null },
    { id: 'mock/careful', provider: 'mock', model: 'careful', purposes: [], available: true, reason: null },
    { id: 'gemini/pro', provider: 'gemini', model: 'pro', purposes: [], available: false, reason: 'GEMINI_API_KEY is not set' },
  ],
  session_agent: 'mock/fast',
}

const entries = new Map<string, SessionEntry[]>()
const turns = new Map<string, AgentTurn>()
const panelSessions = new Map<string, Session>()
const streams: EventSource[] = []
let counter = 0
const nextId = (prefix: string) => `${prefix}-mock-${++counter}`

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

/** Sends an event on every open live stream, as the backend would. */
function emit(type: string, projectId: string, payload: Record<string, unknown>) {
  const data = JSON.stringify({ type, project_id: projectId, payload, at: new Date().toISOString() })
  for (const stream of streams) if (stream.readyState !== EventSource.CLOSED) stream.dispatchEvent(new MessageEvent(type, { data }))
}

// Read again after each wait: a cancel may have come in meanwhile.
const stopped = (turn: AgentTurn) => turn.status === 'cancelled'

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/** A turn that thinks, calls two tools (one fails), cites a source and answers. */
async function play(turn: AgentTurn, projectId: string, question: string, context: Context[]) {
  const send = (index: number, part: Part) => {
    turn.parts[index] = part
    emit('agent.turn_part', projectId, { session_id: turn.session_id, turn_id: turn.id, index, part })
  }
  await wait(400)
  turn.status = 'running'
  emit('agent.turn_started', projectId, { session_id: turn.session_id, turn_id: turn.id })
  const thought = `The question is “${question}”. ${context.length ? `It comes with ${context.length} piece(s) of context. ` : ''}I will look at the pipeline’s output first, then answer.`
  for (let end = 12; end < thought.length + 12; end += 12) {
    if (stopped(turn)) return
    send(0, { type: 'reasoning', text: thought.slice(0, end) })
    await wait(120)
  }
  const sql = { sql: 'SELECT county, participation FROM input_0 ORDER BY participation' }
  send(1, { type: 'tool', tool_call_id: 'c1', tool_name: 'preview_rows', state: 'input-available', input: sql, output: null, error_text: null })
  await wait(1200)
  if (stopped(turn)) return
  send(1, { type: 'tool', tool_call_id: 'c1', tool_name: 'preview_rows', state: 'output-available', input: sql, output: { rows: 21, first: ['Lappi', 71.2] }, error_text: null })
  send(2, { type: 'tool', tool_call_id: 'c2', tool_name: 'create_widget', state: 'output-error', input: { type: 'map' }, output: null, error_text: 'This is the mock agent: it makes no widgets.' })
  send(3, { type: 'source', source_id: 'mock-source', title: 'Sotkanet screening participation', url: 'https://sotkanet.fi' })
  const answer = 'Participation was lowest in Lappi (71 %) and highest in Pirkanmaa. This answer comes from the development mock, not from a model.'
  for (let end = 6; end < answer.length + 6; end += 6) {
    if (stopped(turn)) return
    send(4, { type: 'text', text: answer.slice(0, end) })
    await wait(60)
  }
  turn.status = 'done'
  turn.finished_at = new Date().toISOString()
  emit('agent.turn_finished', projectId, { session_id: turn.session_id, turn_id: turn.id, status: 'done' })
}

async function pipelinesOf(projectId: string, real: typeof fetch): Promise<Pipeline[]> {
  const widgets = (await (await real(`/api/projects/${projectId}/widgets`)).json()) as { operator_id: string; title: string }[]
  const seen = new Map<string, string>()
  for (const widget of widgets) if (!seen.has(widget.operator_id)) seen.set(widget.operator_id, widget.title || 'A pipeline')
  return Promise.all(
    [...seen].map(async ([operatorId, name]) => {
      const operator = await (await real(`/api/operators/${operatorId}`)).json()
      return { operator_id: operatorId, name, kind: operator.kind, sources: [], output: operator.output, created_at: operator.created_at }
    }),
  )
}

export function installMockAgent() {
  const real = window.fetch.bind(window)
  const RealEventSource = window.EventSource
  // Keeps the page's live streams, so the mock can send events on them.
  window.EventSource = class extends RealEventSource {
    constructor(url: string | URL, init?: EventSourceInit) {
      super(url, init)
      streams.push(this)
    }
  }

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = new Request(input, init)
    const { pathname } = new URL(request.url, window.location.origin)
    const method = request.method
    let match: RegExpExecArray | null

    if (method === 'GET' && pathname === '/api/llm/models') return respond(models)
    if (method === 'GET' && (match = /^\/api\/projects\/([^/]+)\/pipelines$/.exec(pathname)))
      return respond(await pipelinesOf(match[1], real))
    if (method === 'GET' && (match = /^\/api\/turns\/([^/]+)$/.exec(pathname))) {
      const turn = turns.get(match[1])
      return turn ? respond({ ...turn, parts: [...turn.parts] }) : respond({ detail: 'turn not found' }, 404)
    }
    if (method === 'POST' && (match = /^\/api\/turns\/([^/]+)\/cancel$/.exec(pathname))) {
      const turn = turns.get(match[1])
      if (turn && (turn.status === 'queued' || turn.status === 'running')) {
        turn.status = 'cancelled'
        turn.finished_at = new Date().toISOString()
        const projectId = sessionProjects.get(turn.session_id) ?? ''
        emit('agent.turn_finished', projectId, { session_id: turn.session_id, turn_id: turn.id, status: 'cancelled' })
      }
      return respond({}, 202)
    }
    if (method === 'POST' && (match = /^\/api\/dashboards\/([^/]+)\/agent-session$/.exec(pathname))) {
      const dashboardId = match[1]
      let session = panelSessions.get(dashboardId)
      if (!session) {
        const view = await (await real(`/api/dashboards/${dashboardId}`)).json()
        session = {
          id: nextId('session'),
          project_id: view.dashboard.project_id,
          title: `${view.dashboard.name} (agent)`,
          origin_dashboard_id: dashboardId,
          panel_dashboard_id: dashboardId,
          created_at: new Date().toISOString(),
          revision: 1,
        }
        panelSessions.set(dashboardId, session)
        sessionProjects.set(session.id, session.project_id)
      }
      return respond(session, 201)
    }
    if ((match = /^\/api\/sessions\/([^/]+)\/(entries|widgets|messages)$/.exec(pathname))) {
      const [, sessionId, what] = match
      const mockSession = sessionId.includes('-mock-')
      if (method === 'GET' && what === 'widgets' && mockSession) return respond([])
      if (method === 'GET' && what === 'entries') {
        const stored = mockSession ? [] : ((await (await real(request)).json()) as SessionEntry[])
        return respond([...stored, ...(entries.get(sessionId) ?? [])])
      }
      if (method === 'POST' && what === 'messages') {
        const body = (await request.json()) as { text: string; context?: Context[]; model?: string }
        const projectId = sessionProjects.get(sessionId) ?? (await (await real(`/api/sessions/${sessionId}`)).json()).project_id
        sessionProjects.set(sessionId, projectId)
        const now = new Date().toISOString()
        const entry: SessionEntry = {
          id: nextId('entry'),
          session_id: sessionId,
          kind: 'message',
          text: body.text,
          ref: null,
          actor: { kind: 'user', name: 'web' },
          created_at: now,
          context: body.context ?? [],
        }
        const turn: AgentTurn = {
          id: nextId('turn'),
          session_id: sessionId,
          prompt_entry_id: entry.id,
          model: body.model ?? models.session_agent!,
          status: 'queued',
          parts: [],
          error: null,
          created_at: now,
          finished_at: null,
        }
        turns.set(turn.id, turn)
        const turnEntry: SessionEntry = {
          id: nextId('entry'),
          session_id: sessionId,
          kind: 'agent_turn',
          text: '',
          ref: turn.id,
          actor: { kind: 'agent', name: turn.model },
          created_at: now,
        }
        entries.set(sessionId, [...(entries.get(sessionId) ?? []), entry, turnEntry])
        emit('session.entry_added', projectId, { session_id: sessionId, entry_id: entry.id })
        void play(turn, projectId, body.text, body.context ?? [])
        return respond({ entry, turn: { ...turn, parts: [] } }, 201)
      }
    }
    return real(request)
  }
  console.info('ADA: the development mock agent answers the wave 3 routes (?mock-agent=0 turns it off).')
}

const sessionProjects = new Map<string, string>()
