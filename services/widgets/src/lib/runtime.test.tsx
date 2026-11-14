import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import { coverage, widget } from '@/test/samples'

import { WidgetRuntime } from './runtime'
import type { WidgetData } from './types'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

/** Answers the two requests a widget makes. */
function serve({ data = coverage() } = {} as { data?: WidgetData }) {
  const fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.startsWith('/api/widgets/w1/data')) return json(data)
    if (url === '/api/widgets/w1') return json(widget())
    return json({ detail: 'unexpected' }, 500)
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

function show(hash = '#widget=w1') {
  window.location.hash = hash
  render(<WidgetRuntime>{({ data, roles }) => <p>{`${data.rows.length} rows, ${roles.measures?.length ?? 0} measures`}</p>}</WidgetRuntime>)
}

test('loads the widget, its data and its roles from the fragment', async () => {
  const fetch = serve()
  show('#widget=w1&run=r9')

  expect(screen.getByRole('status')).toHaveTextContent('Loading')
  expect(await screen.findByText('6 rows, 1 measures')).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledWith('/api/widgets/w1/data?limit=1000&run_id=r9')
  expect(screen.queryByRole('list', { name: 'Data warnings' })).not.toBeInTheDocument()
})

test('marks scenario data', async () => {
  serve({ data: coverage({ is_scenario: true }) })
  show()

  const flags = await screen.findByRole('list', { name: 'Data warnings' })
  expect(flags).toHaveTextContent('Scenario: simulated numbers')
  expect(flags).not.toHaveTextContent('Stale')
})

test('marks stale data', async () => {
  serve({ data: coverage({ is_stale: true }) })
  show()

  const flags = await screen.findByRole('list', { name: 'Data warnings' })
  expect(flags).toHaveTextContent('Stale')
  expect(flags).not.toHaveTextContent('Scenario')
})

test('marks data that is both simulated and stale', async () => {
  serve({ data: coverage({ is_scenario: true, is_stale: true }) })
  show()

  expect(await screen.findAllByRole('listitem')).toHaveLength(2)
})

test('shows data whose output declares no roles', async () => {
  serve({ data: coverage({ output: { columns: [] } }) })
  show()

  expect(await screen.findByText('6 rows, 0 measures')).toBeInTheDocument()
})

test('shows the server error', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => json({ detail: 'Widget w1 not found' }, 404)),
  )
  show()

  expect(await screen.findByRole('alert')).toHaveTextContent('Widget w1 not found')
})

test('says so when the address names no widget', async () => {
  serve()
  show('')

  expect(await screen.findByRole('alert')).toHaveTextContent('names no widget')
})
