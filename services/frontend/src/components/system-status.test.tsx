import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import type { Health } from '@/lib/api'

import { SystemStatus } from './system-status'

function renderStatus() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <SystemStatus />
    </QueryClientProvider>,
  )
}

test('shows each part of a degraded system', async () => {
  const health: Health = {
    status: 'degraded',
    api: 'ok',
    database: 'ok',
    queue: 'unavailable',
    worker: 'unavailable',
    analysis_store: 'ok',
  }
  // A degraded backend answers 503 with the health body.
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(health), { status: 503 })),
  )

  renderStatus()

  expect(await screen.findByText('Analysis store')).toBeInTheDocument()
  expect(screen.getAllByText('OK')).toHaveLength(3)
  expect(screen.getAllByText('Unavailable')).toHaveLength(2)
})

test('says so when the API cannot be reached', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('bad gateway', { status: 502 })),
  )

  renderStatus()

  expect(await screen.findByRole('alert')).toHaveTextContent('The API cannot be reached.')
})
