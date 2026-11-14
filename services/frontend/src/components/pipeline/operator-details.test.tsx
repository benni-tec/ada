import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import type { Operator } from '@/lib/api'

import { shortName } from './labels'
import { OperatorDetails } from './operator-details'

function operator(overrides: Partial<Operator>): Operator {
  return {
    id: 'op_x',
    project_id: 'p1',
    kind: 'statistic',
    params: {},
    inputs: [],
    output: { kind: 'table', columns: [], roles: { measures: [] }, derived: true },
    materializing: false,
    created_by: { kind: 'external_agent', name: 'Claude Desktop' },
    created_at: '2026-11-01T09:00:00Z',
    ...overrides,
  } as Operator
}

function show(subject: Operator) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <OperatorDetails operator={subject} run={null} sourceOf={() => undefined} nameOf={(id) => `Step ${id}`} />
    </QueryClientProvider>,
  )
  return screen.getByRole('region', { name: new RegExp(shortName(subject)) })
}

test('a statistic shows its tool and arguments, what it reads and who made it', () => {
  const details = show(
    operator({ params: { tool: 'wilson_interval', arguments: { level: 0.95 } }, inputs: ['op_a'] }),
  )
  expect(details).toHaveTextContent('Statistic')
  expect(details).toHaveTextContent('wilson_interval')
  expect(within(details).getByText(/"level": 0.95/)).toBeInTheDocument()
  expect(details).toHaveTextContent('ReadsStep op_a')
  expect(details).toHaveTextContent('External agent: ↗Claude Desktop')
  expect(details).toHaveTextContent('Only its definition; computed from its inputs when read (pass-through)')
  expect(details).toHaveTextContent('The columns are not known until the data is read.')
})

test('an agent step is materializing, and says so before the run has a snapshot of it', () => {
  const details = show(operator({ kind: 'agent', params: { prompt: 'Recommend where to act first', model: 'm' }, materializing: true }))
  expect(details).toHaveTextContent('Recommend where to act first')
  expect(details).toHaveTextContent('A snapshot of its output (materializing)')
  // Without the card's run there is nothing to say about a snapshot yet.
  expect(within(details).queryByRole('region', { name: 'Snapshot in this run' })).not.toBeInTheDocument()
})
