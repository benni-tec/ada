import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import { dashboard, json, project, renderAt, serveApi, session } from './app'

// The projects page, a project's overview and the frame of every project page: the sidebar,
// the type above each title, the theme.

const source = {
  id: 'ds1',
  project_id: 'p1',
  name: 'Sotkanet screening',
  access_kind: 'url',
  address: 'https://sotkanet.test',
  format: 'json',
  options: {},
  freshness: { kind: 'manual' },
  declared_schema: null,
  created_at: '2026-11-01T09:00:00Z',
  last_checked_at: null,
  last_probe_token: null,
  last_error: 'HTTP 503',
  revision: 1,
}

function serveProject(overrides: Record<string, unknown> = {}) {
  return serveApi({
    'GET /api/projects': [project(), project({ id: 'p2', name: 'Mortality study' })],
    'GET /api/projects/p1': project(),
    'GET /api/projects/p1/sessions': [session(), session({ id: 's2', title: 'Mortality', created_at: '2026-11-02T09:00:00Z' })],
    'GET /api/projects/p1/dashboards': [dashboard({ current_version_id: null })],
    'GET /api/projects/p1/reports': [
      { id: 'rep1', project_id: 'p1', name: 'Findings', session_id: null, dashboard_id: 'd1', latest_version_id: null, created_at: '2026-11-03T09:00:00Z', revision: 1 },
    ],
    'GET /api/projects/p1/alerts': [{ alert: { id: 'a1', state: 'firing' }, rule: { severity: 'critical' } }],
    'GET /api/projects/p1/sources': [source],
    'POST /api/projects/p1/runs': json({ id: 'r1', project_id: 'p1', snapshots: {} }, 201),
    ...overrides,
  })
}

const nav = () => screen.getByRole('navigation', { name: 'Project' })
const group = (name: string) => within(nav()).getByRole('group', { name })

test('the projects page lists the projects and the system’s state, and creates a project and opens it', async () => {
  const created: unknown[] = []
  serveApi({
    'GET /api/projects': [project(), project({ id: 'p2', name: 'Mortality' })],
    // A degraded backend answers 503 with the health body.
    'GET /api/health': json({ status: 'degraded', api: 'ok', database: 'ok', queue: 'unavailable', worker: 'unavailable', analysis_store: 'ok' }, 503),
    'POST /api/projects': (body: unknown) => (created.push(body), project({ id: 'p3', name: 'Vaccination' })),
    'GET /api/projects/p3': project({ id: 'p3', name: 'Vaccination' }),
    'GET /api/projects/p3/sessions': [],
    'GET /api/projects/p3/sources': [],
  })
  const { router } = renderAt('/')

  const links = await within(await screen.findByRole('region', { name: 'All projects' })).findAllByRole('link')
  expect(links.map((link) => link.textContent)).toEqual([expect.stringContaining('Screening'), expect.stringContaining('Mortality')])
  expect(links[1]).toHaveAttribute('href', '/projects/p2')
  const status = await screen.findByRole('region', { name: 'System status' })
  expect(within(status).getAllByText('Unavailable')).toHaveLength(2)

  fireEvent.change(screen.getByLabelText('New project'), { target: { value: 'Vaccination' } })
  fireEvent.click(screen.getByRole('button', { name: 'Create project' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/projects/p3'))
  expect(await screen.findByRole('heading', { name: 'Vaccination', level: 1 })).toBeInTheDocument()
  expect(created).toEqual([{ name: 'Vaccination' }])
})

test('the overview counts the project’s items, and the sidebar lists them under the project switcher', async () => {
  serveProject()
  renderAt('/projects/p1')

  // The overview: counts, the newest sessions, the sources' state.
  expect(await screen.findByRole('heading', { name: 'Screening', level: 1 })).toBeInTheDocument()
  const counts = screen.getByRole('list', { name: 'In this project' })
  await waitFor(() => expect(counts).toHaveTextContent('Sessions2'))
  expect(counts).toHaveTextContent('Data sources1')
  const recent = screen.getByRole('region', { name: 'Recent sessions' })
  expect(await within(recent).findByRole('link', { name: /Why did coverage drop\?/ })).toHaveAttribute('href', '/projects/p1/sessions/s1')
  const sources = screen.getByRole('region', { name: 'Data sources' })
  expect(await within(sources).findByText(/Last refresh failed: HTTP 503/)).toBeInTheDocument()
  expect(screen.getByRole('status', { name: 'Live updates: Connecting' })).toBeInTheDocument()

  // The sidebar's header names the project and switches to another, or back to all of them.
  fireEvent.keyDown(screen.getByRole('button', { name: /Project\s*Screening.*switch project/ }), { key: 'Enter' })
  const menu = await screen.findByRole('menu')
  expect(await within(menu).findByRole('menuitem', { name: 'Mortality study' })).toHaveAttribute('href', '/projects/p2')
  expect(within(menu).getByRole('menuitem', { name: 'All projects' })).toHaveAttribute('href', '/')
  fireEvent.keyDown(menu, { key: 'Escape' })

  // Then each type, newest first.
  expect(within(nav()).getByRole('link', { name: 'Overview' })).toHaveAttribute('href', '/projects/p1')
  await waitFor(() =>
    expect(within(group('Sessions')).getAllByRole('link').map((link) => link.textContent)).toEqual(['Mortality', 'Why did coverage drop?']),
  )
  expect(await within(group('Dashboards')).findByRole('link', { name: 'Screening overview' })).toHaveAttribute('href', '/projects/p1/dashboards/d1')
  expect(await within(group('Reports')).findByRole('link', { name: 'Findings' })).toHaveAttribute('href', '/projects/p1/reports/rep1')
  expect(within(group('Reports')).getByRole('link', { name: 'Generate a report' })).toHaveAttribute('href', '/projects/p1/reports/new')
  const alerts = within(nav()).getByRole('link', { name: 'Alerts' })
  expect(alerts).toHaveAttribute('href', '/projects/p1/alerts')
  expect(await within(alerts.closest('li')!).findByText('1')).toBeInTheDocument()
  // Data sources are folded at first, and have no page: each leads to its card on the overview.
  const folded = within(group('Data sources')).getByRole('button', { name: 'Data sources' })
  expect(folded).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(folded)
  expect(await within(group('Data sources')).findByRole('link', { name: /Sotkanet screening/ })).toHaveAttribute('href', '/projects/p1#source-ds1')
})

test('the sidebar collapses to icons and opens again, and creates sessions and dashboards, marking the current one', async () => {
  const created: unknown[] = []
  const waiting = session({ id: 's9', title: 'Waiting times', created_at: '2026-11-04T09:00:00Z' })
  serveProject({
    'GET /api/projects/p1/sessions': () => [session(), ...(created.length ? [waiting] : [])],
    'POST /api/projects/p1/sessions': (body: unknown) => (created.push(body), json(waiting, 201)),
    'GET /api/sessions/s9': waiting,
    'GET /api/sessions/s9/entries': [],
    'GET /api/sessions/s9/widgets': [],
    'POST /api/projects/p1/dashboards': (body: unknown) => (created.push(body), json(dashboard({ id: 'd8', name: 'Mortality' }), 201)),
    'GET /api/dashboards/d8': { dashboard: dashboard({ id: 'd8', name: 'Mortality', current_version_id: null }), version: null },
    'GET /api/dashboards/d8/versions': [],
    'GET /api/projects/p1/widgets': [],
  })
  const { router } = renderAt('/projects/p1')
  await screen.findByRole('navigation', { name: 'Project' })

  // Collapsed to icons, a type's icon opens the sidebar again.
  const sidebar = document.querySelector('[data-slot="sidebar"][data-state]')!
  fireEvent.click(screen.getAllByRole('button', { name: 'Toggle Sidebar' })[0])
  await waitFor(() => expect(sidebar).toHaveAttribute('data-collapsible', 'icon'))
  fireEvent.click(within(group('Dashboards')).getByRole('button', { name: 'Dashboards' }))
  await waitFor(() => expect(sidebar).toHaveAttribute('data-state', 'expanded'))

  fireEvent.click(await within(group('Sessions')).findByRole('button', { name: 'New session' }))
  let dialog = await screen.findByRole('dialog', { name: 'New session' })
  fireEvent.change(within(dialog).getByLabelText('Title'), { target: { value: 'Waiting times' } })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Start session' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/projects/p1/sessions/s9'))

  // The page names its type above its title (no breadcrumbs); the sidebar marks it.
  const heading = await screen.findByRole('heading', { name: 'Waiting times', level: 1 })
  const label = document.querySelector('[data-page-type="session"]')!
  expect(label).toHaveTextContent('Session')
  expect(label.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(screen.queryByRole('navigation', { name: 'Breadcrumb' })).not.toBeInTheDocument()
  const current = await within(group('Sessions')).findByRole('link', { name: 'Waiting times' })
  await waitFor(() => expect(current).toHaveAttribute('aria-current', 'page'))
  expect(within(group('Sessions')).getByRole('link', { name: 'Why did coverage drop?' })).not.toHaveAttribute('aria-current')

  fireEvent.click(within(group('Dashboards')).getByRole('button', { name: 'New dashboard' }))
  dialog = await screen.findByRole('dialog', { name: 'New dashboard' })
  fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'Mortality' } })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Create dashboard' }))
  await waitFor(() => expect(router.state.location.pathname).toBe('/projects/p1/dashboards/d8'))
  expect(await screen.findByText(/No versions yet/)).toBeInTheDocument()
  expect(created).toEqual([{ title: 'Waiting times' }, { name: 'Mortality' }])
})

test('the theme can be set apart from the system’s, and the page follows it', async () => {
  serveProject()
  renderAt('/projects/p1')

  fireEvent.pointerDown(await screen.findByRole('button', { name: 'Theme' }), { button: 0, ctrlKey: false })
  fireEvent.click(await screen.findByRole('menuitemradio', { name: 'Dark' }))
  await waitFor(() => expect(document.documentElement).toHaveClass('dark'))
  expect(localStorage.getItem('ada-theme')).toBe('dark')

  fireEvent.pointerDown(screen.getByRole('button', { name: 'Theme' }), { button: 0, ctrlKey: false })
  fireEvent.click(await screen.findByRole('menuitemradio', { name: 'As the system' }))
  await waitFor(() => expect(document.documentElement).not.toHaveClass('dark'))
})
