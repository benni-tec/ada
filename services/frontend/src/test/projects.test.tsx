import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import { json, project, renderAt, serveApi, session } from './app'

const health = { status: 'ok', api: 'ok', database: 'ok', queue: 'ok', worker: 'ok', analysis_store: 'ok' }

test('lists the projects', async () => {
  serveApi({
    'GET /api/projects': [project(), project({ id: 'p2', name: 'Mortality' })],
    'GET /api/health': health,
  })

  renderAt('/')

  const list = await screen.findByRole('region', { name: 'All projects' })
  const links = await within(list).findAllByRole('link')
  expect(links.map((link) => link.textContent)).toEqual([
    expect.stringContaining('Screening'),
    expect.stringContaining('Mortality'),
  ])
  expect(links[1]).toHaveAttribute('href', '/projects/p2')
})

test('creates a project and opens it', async () => {
  const created = project({ id: 'p3', name: 'Vaccination' })
  const fetch = serveApi({
    'GET /api/projects': [],
    'POST /api/projects': (body: unknown) => (expect(body).toEqual({ name: 'Vaccination' }), created),
    'GET /api/projects/p3': created,
    'GET /api/projects/p3/sessions': [],
    'GET /api/projects/p3/sources': [],
    'GET /api/health': health,
  })
  const { router } = renderAt('/')

  fireEvent.change(await screen.findByLabelText('New project'), { target: { value: 'Vaccination' } })
  fireEvent.click(screen.getByRole('button', { name: 'Create project' }))

  await waitFor(() => expect(router.state.location.pathname).toBe('/projects/p3'))
  expect(await screen.findByRole('heading', { name: 'Vaccination', level: 1 })).toBeInTheDocument()
  expect(fetch).toHaveBeenCalled()
})

test('shows the detail of a failed call', async () => {
  serveApi({
    'GET /api/projects': json({ detail: 'The database is not reachable' }, 503),
    'GET /api/health': health,
  })

  renderAt('/')

  expect(await screen.findByText(/The database is not reachable/)).toBeInTheDocument()
})

test('the project page is an overview: counts, recent sessions and the sources’ state', async () => {
  serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/projects/p1/sessions': [session()],
    'GET /api/projects/p1/dashboards': [],
    'GET /api/projects/p1/reports': [],
    'GET /api/projects/p1/alerts': [],
    'GET /api/projects/p1/sources': [source],
  })

  renderAt('/projects/p1')

  expect(await screen.findByRole('heading', { name: 'Screening', level: 1 })).toBeInTheDocument()
  const counts = screen.getByRole('list', { name: 'In this project' })
  await waitFor(() => expect(counts).toHaveTextContent('Sessions1'))
  expect(counts).toHaveTextContent('Data sources1')
  const recent = screen.getByRole('region', { name: 'Recent sessions' })
  expect(await within(recent).findByRole('link', { name: /Why did coverage drop\?/ })).toHaveAttribute(
    'href',
    '/projects/p1/sessions/s1',
  )
  const sources = screen.getByRole('region', { name: 'Data sources' })
  expect(await within(sources).findByText('Screening coverage')).toBeInTheDocument()
  expect(within(sources).getByText(/Last refresh failed: HTTP 503/)).toBeInTheDocument()
  // Widgets are no longer listed here: they live in their sessions and dashboards.
  expect(screen.queryByRole('region', { name: 'Widgets' })).not.toBeInTheDocument()
  expect(screen.getByRole('status', { name: 'Live updates: Connecting' })).toBeInTheDocument()
})

const source = {
  id: 'd1',
  project_id: 'p1',
  name: 'Screening coverage',
  access_kind: 'url',
  address: 'https://example.org/coverage.csv',
  format: 'csv',
  options: {},
  freshness: { kind: 'ttl', ttl_seconds: 86400, latest_period_ttl_seconds: null },
  declared_schema: null,
  created_at: '2026-11-01T09:00:00Z',
  last_checked_at: null,
  last_probe_token: null,
  last_error: 'HTTP 503',
  revision: 1,
}
