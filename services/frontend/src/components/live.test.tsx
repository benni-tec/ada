import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { retryDelay, useLive } from '@/lib/live'
import { FakeEventSource, stubEventSource } from '@/test/app'

import { ConnectionIndicator, ProjectLive } from './live'

function Epoch() {
  return <p>epoch {useLive().widgetEpoch}</p>
}

function renderLive(queryClient = new QueryClient()) {
  render(
    <QueryClientProvider client={queryClient}>
      <ProjectLive projectId="p1">
        <ConnectionIndicator />
        <Epoch />
      </ProjectLive>
    </QueryClientProvider>,
  )
  return queryClient
}

beforeEach(() => {
  vi.useFakeTimers()
  stubEventSource()
})

afterEach(() => {
  vi.useRealTimers()
})

test('backs off up to 30 seconds', () => {
  expect([0, 1, 2, 3, 4, 5, 6].map(retryDelay)).toEqual([1000, 2000, 4000, 8000, 16000, 30000, 30000])
})

test('reconnects with backoff and refetches everything after a reconnect', () => {
  const queryClient = renderLive()
  const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
  expect(screen.getByRole('status')).toHaveAccessibleName('Live updates: Connecting')

  act(() => FakeEventSource.latest().open())
  expect(screen.getByRole('status')).toHaveAccessibleName('Live updates: Live')
  expect(invalidate).not.toHaveBeenCalled()

  const first = FakeEventSource.latest()
  act(() => first.fail())
  expect(first.closed).toBe(true)
  expect(screen.getByRole('status')).toHaveAccessibleName('Live updates: Reconnecting')

  act(() => vi.advanceTimersByTime(999))
  expect(FakeEventSource.instances).toHaveLength(1)
  act(() => vi.advanceTimersByTime(1))
  expect(FakeEventSource.instances).toHaveLength(2)

  // A second failure before opening waits longer.
  act(() => FakeEventSource.latest().fail())
  act(() => vi.advanceTimersByTime(1999))
  expect(FakeEventSource.instances).toHaveLength(2)
  act(() => vi.advanceTimersByTime(1))
  expect(FakeEventSource.instances).toHaveLength(3)

  act(() => FakeEventSource.latest().open())
  expect(screen.getByRole('status')).toHaveAccessibleName('Live updates: Live')
  // Events may have been missed while away: refetch everything, reload widgets.
  expect(invalidate).toHaveBeenCalledWith()
  expect(screen.getByText('epoch 1')).toBeInTheDocument()
})

test('reloads widget frames when a source brought new data', () => {
  const queryClient = renderLive()
  const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
  const stream = FakeEventSource.latest()
  act(() => stream.open())

  act(() =>
    stream.emit('source.refreshed', {
      type: 'source.refreshed',
      project_id: 'p1',
      payload: { data_source_id: 'd1', changed: true },
      at: '2026-11-01T10:00:00Z',
    }),
  )

  expect(screen.getByText('epoch 1')).toBeInTheDocument()
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ['projects', 'p1', 'sources'] })
})

test('closes the stream when the project is left', () => {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <ProjectLive projectId="p1">
        <span />
      </ProjectLive>
    </QueryClientProvider>,
  ).unmount()

  expect(FakeEventSource.latest().closed).toBe(true)
})
