import { fireEvent, render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'

import { coverage, loaded, widget } from '@/test/samples'

import { LineChart } from './line-chart'
import { buildChart, niceTicks, runs, type ChartModel } from './model'

const bySeries = widget({ type: 'line-chart', spec: { series: 'region' } })

test('builds one series per region from the roles', () => {
  const model = buildChart(loaded({ widget: bySeries })) as ChartModel

  expect(model.x).toBe('period_start')
  expect(model.y).toBe('coverage')
  expect(model.xKind).toBe('time')
  expect(model.series.map((series) => series.key)).toEqual(['North', 'South'])
  expect(model.hasBand).toBe(true)
  expect(model.hasSuppressed).toBe(true)
  // The suppressed value is a gap, which splits North into two runs.
  expect(runs(model.series[0].points)).toHaveLength(2)
  expect(runs(model.series[1].points)).toHaveLength(1)
})

test('draws no band when the schema declares no bounds', () => {
  const model = buildChart(loaded({ widget: bySeries, roles: { measures: [{ value: 'coverage' }] } })) as ChartModel

  expect(model.hasBand).toBe(false)
  expect(model.hasSuppressed).toBe(false)
})

test('renders lines, bands, a dot between gaps and a legend', () => {
  const { container } = render(<LineChart {...loaded({ widget: bySeries })} />)

  expect(screen.getByRole('img')).toHaveAccessibleName(
    'Screening coverage: Line chart of coverage by period_start, 2 series, from 2022 to 2024',
  )
  // North: 2022 and 2024 are each alone between gaps, so they are dots, not lines.
  const north = container.querySelector('[data-series="North"]')!
  expect(north.querySelectorAll('circle')).toHaveLength(2)
  expect(north.querySelectorAll('.ada-line')).toHaveLength(0)
  const south = container.querySelector('[data-series="South"]')!
  expect(south.querySelectorAll('.ada-line')).toHaveLength(1)
  expect(south.querySelectorAll('.ada-band')).toHaveLength(1)

  const legend = screen.getByRole('list', { name: 'Legend' })
  expect(legend).toHaveTextContent('North')
  expect(legend).toHaveTextContent('South')
  expect(legend).toHaveTextContent('Shaded: confidence interval')
  expect(legend).toHaveTextContent('Gaps: suppressed values')
})

test('shows the values at an x with the keyboard', () => {
  render(<LineChart {...loaded({ widget: bySeries })} />)

  fireEvent.keyDown(screen.getByRole('img'), { key: 'ArrowRight' })
  fireEvent.keyDown(screen.getByRole('img'), { key: 'ArrowRight' })

  const tooltip = screen.getByRole('status')
  expect(tooltip).toHaveTextContent('2023')
  expect(tooltip).toHaveTextContent('Northsuppressed')
  expect(tooltip).toHaveTextContent('South71 (69–73)')
})

test('uses x and y from the spec and a category axis for text', () => {
  const data = coverage({
    columns: [
      { name: 'month', type: 'text' },
      { name: 'visits', type: 'integer' },
    ],
    rows: [
      ['Jan', 10],
      ['Feb', 12],
      ['Mar', 9],
    ],
  })
  const spec = { x: 'month', y: 'visits' }
  render(<LineChart {...loaded({ widget: widget({ title: '', spec }), data, roles: {} })} />)

  expect(screen.getByRole('img')).toHaveAccessibleName('Line chart of visits by month, from Jan to Mar')
  expect(screen.queryByRole('list', { name: 'Legend' })).not.toBeInTheDocument()
})

test('names a missing column', () => {
  render(<LineChart {...loaded({ widget: widget({ spec: { y: 'deaths' } }) })} />)

  expect(screen.getByRole('alert')).toHaveTextContent('No column "deaths" for the y axis')
})

test('ticks are round and cover the range', () => {
  expect(niceTicks(3, 17)).toEqual([0, 5, 10, 15, 20])
  expect(niceTicks(0.1, 0.3)).toEqual([0.1, 0.15, 0.2, 0.25, 0.3])
  expect(niceTicks(5, 5).length).toBeGreaterThan(1)
})
