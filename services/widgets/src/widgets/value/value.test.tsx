import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'

import { coverage, loaded, widget } from '@/test/samples'

import { Value } from './value'

const south = coverage({ rows: coverage().rows.filter((row) => row[2] === 'South') })

test('shows the measure of the latest period with its interval', () => {
  render(<Value {...loaded({ data: south })} />)

  expect(screen.getByText('72.5')).toBeInTheDocument()
  expect(screen.getByRole('figure')).toHaveTextContent('coverage · 2024')
  expect(screen.getByText('Interval 70 – 75')).toBeInTheDocument()
})

test('uses the label, unit and column from the spec', () => {
  const spec = { column: 'coverage_low', label: 'Lower bound', unit: '%' }
  render(<Value {...loaded({ widget: widget({ spec }), data: south })} />)

  expect(screen.getByText('70')).toBeInTheDocument()
  expect(screen.getByText('%')).toBeInTheDocument()
  expect(screen.getByRole('figure')).toHaveTextContent('Lower bound · 2024')
})

test('says a suppressed value is suppressed instead of showing a number', () => {
  const north2023 = coverage({ rows: [coverage().rows[1]] })
  render(<Value {...loaded({ data: north2023 })} />)

  expect(screen.getByText('Suppressed')).toBeInTheDocument()
  expect(screen.queryByText(/Interval/)).not.toBeInTheDocument()
})

test('falls back to the first numeric column without roles', () => {
  render(<Value {...loaded({ roles: {}, data: south })} />)

  // The last row, since without a time role there is no latest period.
  expect(screen.getByText('72.5')).toBeInTheDocument()
  expect(screen.getByRole('figure')).toHaveTextContent('coverage')
})

test('names a missing column', () => {
  render(<Value {...loaded({ widget: widget({ spec: { column: 'deaths' } }) })} />)

  expect(screen.getByText('No column "deaths" in the data')).toBeInTheDocument()
})
