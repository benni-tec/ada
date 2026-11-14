import { render, screen, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import { coverage, loaded, widget } from '@/test/samples'

import { Table } from './table'

test('shows every column and row, or the columns the spec names, and says when rows were left out', () => {
  const { rerender } = render(<Table {...loaded()} />)
  expect(screen.getAllByRole('columnheader')).toHaveLength(7)
  // A header row plus six rows.
  expect(screen.getAllByRole('row')).toHaveLength(7)
  expect(screen.queryByRole('note')).not.toBeInTheDocument()

  rerender(<Table {...loaded({ widget: widget({ spec: { columns: ['region', 'coverage', 'nope'] } }) })} />)
  expect(screen.getAllByRole('columnheader').map((header) => header.textContent)).toEqual(['region', 'coverage'])
  const north2023 = screen.getAllByRole('row')[2]
  expect(within(north2023).getAllByRole('cell').map((cell) => cell.textContent)).toEqual(['North', 'suppressed'])

  rerender(<Table {...loaded({ data: coverage({ truncated: true }) })} />)
  expect(screen.getByRole('note')).toHaveTextContent('Showing the first 6 rows; there are more.')
})
