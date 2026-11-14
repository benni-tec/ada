import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import { json, project, renderAt, serveApi, session } from './app'

// The frame of every project page: the sidebar, the type above each title, renaming.

const dashboard = {
  id: 'd1',
  project_id: 'p1',
  name: 'Screening overview',
  current_version_id: null,
  default_time_range: { start: null, end: null },
  created_at: '2026-11-01T08:00:00Z',
  revision: 1,
}

function serveProject(overrides: Record<string, unknown> = {}) {
  return serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/projects/p1/sessions': [session(), session({ id: 's2', title: 'Mortality', created_at: '2026-11-02T09:00:00Z' })],
    'GET /api/projects/p1/dashboards': [dashboard],
    'GET /api/projects/p1/reports': [
      { id: 'rep1', project_id: 'p1', name: 'Findings', session_id: null, dashboard_id: 'd1', latest_version_id: null, created_at: '2026-11-03T09:00:00Z', revision: 1 },
    ],
    'GET /api/projects/p1/alerts': [{ alert: { id: 'a1' }, rule: { severity: 'critical' } }],
    'GET /api/projects/p1/sources': [
      { id: 'ds1', name: 'Sotkanet screening', last_error: null, access_kind: 'url', format: 'json', address: 'https://sotkanet.test', freshness: { kind: 'manual' } },
    ],
    'GET /api/sessions/s1': session(),
    'GET /api/sessions/s1/entries': [],
    'GET /api/sessions/s1/widgets': [],
    'POST /api/projects/p1/runs': json({ id: 'r1', project_id: 'p1', snapshots: {} }, 201),
    ...overrides,
  })
}

const nav = () => screen.getByRole('navigation', { name: 'Project' })
const sidebar = () => screen.findByRole('navigation', { name: 'Project' })
const group = (name: string) => within(nav()).getByRole('group', { name })

test('the sidebar groups the project’s items, newest sessions first, with the project switcher in its header', async () => {
  serveProject({ 'GET /api/projects': [project(), project({ id: 'p2', name: 'Mortality study' })] })
  renderAt('/projects/p1')

  // The header names the project and switches to another, or back to all of them.
  const switcher = await screen.findByRole('button', { name: /Project\s*Screening.*switch project/ })
  fireEvent.keyDown(switcher, { key: 'Enter' })
  const menu = await screen.findByRole('menu')
  expect(await within(menu).findByRole('menuitem', { name: 'Mortality study' })).toHaveAttribute('href', '/projects/p2')
  expect(within(menu).getByRole('menuitem', { name: 'All projects' })).toHaveAttribute('href', '/')
  fireEvent.keyDown(menu, { key: 'Escape' })

  expect(within(nav()).getByRole('link', { name: 'Overview' })).toHaveAttribute('href', '/projects/p1')
  const sessions = group('Sessions')
  await waitFor(() => expect(within(sessions).getAllByRole('link')).toHaveLength(2))
  expect(within(sessions).getAllByRole('link').map((link) => link.textContent)).toEqual(['Mortality', 'Why did coverage drop?'])
  expect(within(sessions).getByRole('button', { name: 'New session' })).toBeInTheDocument()

  expect(await within(group('Dashboards')).findByRole('link', { name: 'Screening overview' })).toHaveAttribute(
    'href',
    '/projects/p1/dashboards/d1',
  )
  expect(within(group('Dashboards')).getByRole('button', { name: 'New dashboard' })).toBeInTheDocument()
  expect(await within(group('Reports')).findByRole('link', { name: 'Findings' })).toHaveAttribute('href', '/projects/p1/reports/rep1')
  expect(within(group('Reports')).getByRole('link', { name: 'Generate a report' })).toHaveAttribute('href', '/projects/p1/reports/new')
  const alerts = within(nav()).getByRole('link', { name: 'Alerts' })
  expect(alerts).toHaveAttribute('href', '/projects/p1/alerts')
  expect(await within(alerts.closest('li')!).findByText('1')).toBeInTheDocument()
  // Data sources are folded at first, and have no page: each leads to its entry in Settings.
  const sources = within(group('Data sources')).getByRole('button', { name: 'Data sources' })
  expect(sources).toHaveAttribute('aria-expanded', 'false')
  fireEvent.click(sources)
  expect(await within(group('Data sources')).findByRole('link', { name: 'Sotkanet screening' })).toHaveAttribute(
    'href',
    '/projects/p1/settings#source-ds1',
  )
})

test('the sidebar collapses to icons, and a type’s icon opens it again', async () => {
  serveProject()
  renderAt('/projects/p1')
  await sidebar()

  const sidebarElement = document.querySelector('[data-slot="sidebar"][data-state]')!
  expect(sidebarElement).toHaveAttribute('data-state', 'expanded')
  fireEvent.click(screen.getAllByRole('button', { name: 'Toggle Sidebar' })[0])
  await waitFor(() => expect(sidebarElement).toHaveAttribute('data-collapsible', 'icon'))

  fireEvent.click(within(group('Dashboards')).getByRole('button', { name: 'Dashboards' }))
  await waitFor(() => expect(sidebarElement).toHaveAttribute('data-state', 'expanded'))
  expect(within(group('Dashboards')).getByRole('button', { name: 'Dashboards' })).toHaveAttribute('aria-expanded', 'true')
})

test('the current item is marked, and every page names its type above its title', async () => {
  serveProject()
  renderAt('/projects/p1/sessions/s1')
  await sidebar()

  const current = await within(group('Sessions')).findByRole('link', { name: 'Why did coverage drop?' })
  await waitFor(() => expect(current).toHaveAttribute('aria-current', 'page'))
  expect(current).toHaveAttribute('data-active', 'true')
  expect(within(group('Sessions')).getByRole('link', { name: 'Mortality' })).not.toHaveAttribute('aria-current')

  // No breadcrumbs: the type, with the sidebar's icon, sits above the title.
  expect(screen.queryByRole('navigation', { name: 'Breadcrumb' })).not.toBeInTheDocument()
  const heading = await screen.findByRole('heading', { name: 'Why did coverage drop?', level: 1 })
  const label = document.querySelector('[data-page-type="session"]')!
  expect(label).toHaveTextContent('Session')
  expect(label.querySelector('svg.lucide-messages-square')).not.toBeNull()
  expect(group('Sessions').querySelector('svg.lucide-messages-square')).not.toBeNull()
  expect(label.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})

test('“New session” asks for a title, creates it and opens it', async () => {
  const created: unknown[] = []
  serveProject({
    'POST /api/projects/p1/sessions': (body: unknown) => {
      created.push(body)
      return json(session({ id: 's9', title: 'Waiting times' }), 201)
    },
    'GET /api/sessions/s9': session({ id: 's9', title: 'Waiting times' }),
    'GET /api/sessions/s9/entries': [],
    'GET /api/sessions/s9/widgets': [],
  })
  const { router } = renderAt('/projects/p1')
  await sidebar()

  fireEvent.click(await within(group('Sessions')).findByRole('button', { name: 'New session' }))
  const dialog = await screen.findByRole('dialog', { name: 'New session' })
  fireEvent.change(within(dialog).getByLabelText('Title'), { target: { value: 'Waiting times' } })
  fireEvent.click(within(dialog).getByRole('button', { name: 'Start session' }))

  await waitFor(() => expect(router.state.location.pathname).toBe('/projects/p1/sessions/s9'))
  expect(created).toEqual([{ title: 'Waiting times' }])
})

test('rename is a pencil: Enter saves, Escape cancels', async () => {
  let stored = project()
  const patches: unknown[] = []
  serveProject({
    'GET /api/projects/p1': () => stored,
    'PATCH /api/projects/p1': (body: unknown) => {
      patches.push(body)
      stored = { ...stored, name: (body as { name: string }).name, revision: stored.revision + 1 }
      return stored
    },
  })
  renderAt('/projects/p1')

  const pencil = await screen.findByRole('button', { name: 'Rename' })
  expect(pencil).toHaveTextContent('')
  expect(pencil.querySelector('svg.lucide-pencil')).not.toBeNull()
  // Its tooltip says what it does.
  act(() => pencil.focus())
  expect(await screen.findByRole('tooltip')).toHaveTextContent('Rename')

  fireEvent.click(pencil)
  const input = screen.getByLabelText('New project name')
  fireEvent.change(input, { target: { value: 'Abandoned' } })
  fireEvent.keyDown(input, { key: 'Escape' })
  expect(screen.queryByLabelText('New project name')).not.toBeInTheDocument()
  expect(patches).toEqual([])

  fireEvent.click(screen.getByRole('button', { name: 'Rename' }))
  fireEvent.change(screen.getByLabelText('New project name'), { target: { value: 'Screening 2026' } })
  fireEvent.submit(screen.getByLabelText('New project name'))
  expect(await screen.findByRole('heading', { name: 'Screening 2026', level: 1 })).toBeInTheDocument()
  expect(patches).toEqual([{ name: 'Screening 2026', expected_revision: 1 }])
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
