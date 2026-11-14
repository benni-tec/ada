import { render, screen, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import { coverage, loaded, widget } from '@/test/samples'

import { Table } from './table'

test('shows every column and row', () => {
  render(<Table {...loaded()} />)

  expect(screen.getAllByRole('columnheader')).toHaveLength(7)
  // A header row plus six rows.
  expect(screen.getAllByRole('row')).toHaveLength(7)
  expect(screen.getByRole('region', { name: 'Screening coverage' })).toHaveAttribute('tabindex', '0')
  expect(screen.queryByRole('note')).not.toBeInTheDocument()
})

test('shows the columns the spec names, in its order', () => {
  render(<Table {...loaded({ widget: widget({ spec: { columns: ['region', 'coverage', 'nope'] } }) })} />)

  const headers = screen.getAllByRole('columnheader').map((header) => header.textContent)
  expect(headers).toEqual(['region', 'coverage'])
  const north2023 = screen.getAllByRole('row')[2]
  expect(within(north2023).getAllByRole('cell').map((cell) => cell.textContent)).toEqual(['North', 'suppressed'])
})

test('says when rows were left out', () => {
  render(<Table {...loaded({ data: coverage({ truncated: true }) })} />)

  expect(screen.getByRole('note')).toHaveTextContent('Showing the first 6 rows; there are more.')
})
