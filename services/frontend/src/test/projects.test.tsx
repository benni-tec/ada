import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import { claude, json, project, renderAt, serveApi, session, widget } from './app'

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

test('shows a project with its sessions, widgets and sources', async () => {
  serveApi({
    'GET /api/projects/p1': project(),
    'GET /api/projects/p1/sessions': [session()],
    'GET /api/sessions/s1/widgets': [widget({ created_by: claude, note: 'Coverage per region over time' })],
    'GET /api/projects/p1/sources': [
      {
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
      },
    ],
  })

  renderAt('/projects/p1')

  const sessions = await screen.findByRole('region', { name: 'Sessions' })
  expect(await within(sessions).findByRole('link', { name: /Why did coverage drop\?/ })).toHaveAttribute(
    'href',
    '/projects/p1/sessions/s1',
  )
  const widgets = screen.getByRole('region', { name: 'Widgets' })
  expect(await within(widgets).findByRole('link', { name: 'Coverage by region' })).toHaveAttribute(
    'href',
    '/projects/p1/widgets/w1',
  )
  expect(within(widgets).getByText('Claude Desktop')).toBeInTheDocument()
  const sources = screen.getByRole('region', { name: 'Data sources' })
  expect(await within(sources).findByText('Screening coverage')).toBeInTheDocument()
  expect(within(sources).getByText(/Last refresh failed: HTTP 503/)).toBeInTheDocument()
  expect(screen.getByRole('status', { name: 'Live updates: Connecting' })).toBeInTheDocument()
})
