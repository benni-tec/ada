// Renders whole routes against a fake API: fetch answers from a table of routes, and
// EventSource is replaced by one the test drives.

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { render } from '@testing-library/react'
import { vi } from 'vitest'

import type {
  Actor,
  AgentTurn,
  Dashboard,
  DashboardSlot,
  LlmModels,
  Pipeline,
  Project,
  Run,
  Session,
  SessionEntry,
  Widget,
} from '@/lib/api'
import { routeTree } from '@/routeTree.gen'

type Handler = (body: unknown, request: Request) => Response | unknown

/** Answers "METHOD /path" with the handler's Response, or its value as a 200 JSON body.
 * Anything else is a 404, so a test notices calls it did not expect. */
export function serveApi(routes: Record<string, Handler | unknown>) {
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const request = new Request(input, init)
    const url = new URL(request.url)
    const route = routes[`${request.method} ${url.pathname}`]
    if (route === undefined) return json({ detail: `No fake for ${request.method} ${url.pathname}` }, 404)
    // A clone, so a handler can still read a body that is not JSON (an upload).
    const body = request.method === 'GET' ? undefined : await request.clone().json().catch(() => undefined)
    const result = typeof route === 'function' ? await (route as Handler)(body, request) : route
    return result instanceof Response ? result : json(result)
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

export function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

/** An EventSource the test opens, fails and feeds by hand. */
export class FakeEventSource {
  static instances: FakeEventSource[] = []
  readonly url: string
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  closed = false
  private listeners = new Map<string, ((message: MessageEvent<string>) => void)[]>()

  constructor(url: string | URL) {
    this.url = String(url)
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: (message: MessageEvent<string>) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener])
  }

  close() {
    this.closed = true
  }

  open() {
    this.onopen?.()
  }

  fail() {
    this.onerror?.()
  }

  emit(type: string, data: unknown) {
    const message = new MessageEvent('message', { data: JSON.stringify(data) })
    for (const listener of this.listeners.get(type) ?? []) listener(message)
  }

  static latest(): FakeEventSource {
    return FakeEventSource.instances[FakeEventSource.instances.length - 1]
  }
}

export function stubEventSource() {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
}

export function renderAt(path: string) {
  stubEventSource()
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createRouter({
    routeTree,
    context: { queryClient },
    history: createMemoryHistory({ initialEntries: [path] }),
  })
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { router, queryClient }
}

// Sample records

export const web: Actor = { kind: 'user', name: 'web' }
export const claude: Actor = { kind: 'external_agent', name: 'Claude Desktop' }

export function project(overrides: Partial<Project> = {}): Project {
  return { id: 'p1', name: 'Screening', created_at: '2026-11-01T09:00:00Z', agent_instructions: '', revision: 1, ...overrides }
}

export function session(overrides: Partial<Session> = {}): Session {
  return {
    id: 's1',
    project_id: 'p1',
    title: 'Why did coverage drop?',
    origin_dashboard_id: null,
    panel_dashboard_id: null,
    agent: 'session',
    created_at: '2026-11-01T09:05:00Z',
    revision: 1,
    ...overrides,
  }
}

export function entry(overrides: Partial<SessionEntry> = {}): SessionEntry {
  return {
    id: 'e1',
    session_id: 's1',
    kind: 'message',
    text: '',
    ref: null,
    context: [],
    actor: web,
    created_at: '2026-11-01T09:06:00Z',
    ...overrides,
  }
}

export function widget(overrides: Partial<Widget> = {}): Widget {
  return {
    id: 'w1',
    project_id: 'p1',
    session_id: 's1',
    operator_id: 'op_1',
    type: 'line-chart',
    title: 'Coverage by region',
    spec: { series: 'region' },
    note: '',
    created_by: web,
    created_at: '2026-11-01T09:10:00Z',
    ...overrides,
  }
}

export function run(id: string, overrides: Partial<Run> = {}): Run {
  return {
    id,
    project_id: 'p1',
    time_range: { start: null, end: null },
    bindings: {},
    snapshots: {},
    started_by: web,
    started_at: '2026-11-03T08:00:00Z',
    ...overrides,
  } as Run
}

export function dashboard(overrides: Partial<Dashboard> = {}): Dashboard {
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

export function slot(name: string, widgetId: string | null, x: number, y: number, w = 6, h = 4): DashboardSlot {
  return { name, description: '', widget_id: widgetId, layout: { x, y, w, h } }
}

// The agent (docs/contracts.md, "The agent")

export function turn(overrides: Partial<AgentTurn> = {}): AgentTurn {
  return {
    id: 't1',
    session_id: 's1',
    prompt_entry_id: 'e1',
    model: 'gemini/flash',
    status: 'running',
    parts: [],
    error: null,
    created_at: '2026-11-01T09:06:01Z',
    finished_at: null,
    ...overrides,
  }
}

export function models(overrides: Partial<LlmModels> = {}): LlmModels {
  return {
    models: [
      { id: 'gemini/flash', provider: 'gemini', model: 'flash', purposes: ['session_agent'], available: true, reason: null },
      { id: 'gemini/pro', provider: 'gemini', model: 'pro', purposes: [], available: true, reason: null },
      {
        id: 'mistral/large',
        provider: 'mistral',
        model: 'large',
        purposes: [],
        available: false,
        reason: 'MISTRAL_API_KEY is not set',
      },
    ],
    session_agent: 'gemini/flash',
    ...overrides,
  }
}

export function pipeline(overrides: Partial<Pipeline> = {}): Pipeline {
  return {
    operator_id: 'op_p1',
    name: 'Screening by county',
    kind: 'transform',
    sources: [{ data_source_id: 'ds1', name: 'Sotkanet screening' }],
    output: {
      kind: 'table',
      columns: [
        { name: 'county', type: 'text', nullable: true },
        { name: 'participation', type: 'number', nullable: true },
      ],
      roles: { measures: [] },
      derived: true,
    } as Pipeline['output'],
    created_at: '2026-11-01T09:00:00Z',
    ...overrides,
  }
}

/** Sends one event on the page's live stream. */
export function emit(type: string, payload: Record<string, unknown>) {
  FakeEventSource.latest().emit(type, { type, project_id: 'p1', payload, at: '2026-11-01T10:00:00Z' })
}
