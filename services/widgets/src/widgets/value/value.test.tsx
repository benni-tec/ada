import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'

import { coverage, loaded, widget } from '@/test/samples'

import { Value } from './value'

const south = coverage({ rows: coverage().rows.filter((row) => row[2] === 'South') })

test('shows the measure of the latest period with its interval, or that it is suppressed', () => {
  const { unmount } = render(<Value {...loaded({ data: south })} />)
  expect(screen.getByText('72.5')).toBeInTheDocument()
  expect(screen.getByRole('figure')).toHaveTextContent('coverage · 2024')
  expect(screen.getByText('Interval 70 – 75')).toBeInTheDocument()
  unmount()

  render(<Value {...loaded({ data: coverage({ rows: [coverage().rows[1]] }) })} />)
  expect(screen.getByText('Suppressed')).toBeInTheDocument()
  expect(screen.queryByText(/Interval/)).not.toBeInTheDocument()
})

test('uses the label, unit and column from the spec, the first numeric column without roles, and names a missing one', () => {
  const spec = { column: 'coverage_low', label: 'Lower bound', unit: '%' }
  const { rerender } = render(<Value {...loaded({ widget: widget({ spec }), data: south })} />)
  expect(screen.getByText('70')).toBeInTheDocument()
  expect(screen.getByText('%')).toBeInTheDocument()
  expect(screen.getByRole('figure')).toHaveTextContent('Lower bound · 2024')

  // The last row, since without a time role there is no latest period.
  rerender(<Value {...loaded({ roles: {}, data: south })} />)
  expect(screen.getByText('72.5')).toBeInTheDocument()

  rerender(<Value {...loaded({ widget: widget({ spec: { column: 'deaths' } }) })} />)
  expect(screen.getByText('No column "deaths" in the data')).toBeInTheDocument()
})
