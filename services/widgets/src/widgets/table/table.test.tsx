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

test('names columns by their labels, writes numbers in their format, and years without separators', () => {
  const data = coverage({
    columns: [
      { name: 'year', type: 'integer' },
      { name: 'birth_year', type: 'integer' },
      { name: 'cases', type: 'integer' },
      { name: 'share', type: 'number' },
      { name: 'code', type: 'integer' },
    ],
    rows: [[2024, 1961, 11970, 72.456, 1234]],
  })
  const spec = {
    labels: { cases: 'Cases', share: 'Share of all' },
    format: { share: 'percent', code: 'plain', nope: 'percent' },
    decimals: 1,
  }
  render(<Table {...loaded({ widget: widget({ type: 'table', spec }), data, roles: {} })} />)

  expect(screen.getAllByRole('columnheader').map((header) => header.textContent)).toEqual([
    'year',
    'birth_year',
    'Cases',
    'Share of all',
    'code',
  ])
  const [year, birthYear, cases, share, code] = within(screen.getAllByRole('row')[1])
    .getAllByRole('cell')
    .map((cell) => cell.textContent)
  expect([year, birthYear, code]).toEqual(['2024', '1961', '1234'])
  // Counts keep their thousands separator, whatever the locale writes it with.
  expect(cases).toBe(new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(11970))
  expect(cases).not.toBe('11970')
  const oneDecimal = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1, minimumFractionDigits: 1 })
  expect(share).toBe(`${oneDecimal.format(72.456)} %`)
})
