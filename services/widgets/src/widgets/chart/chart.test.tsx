import { render, screen, waitFor } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import type { WidgetData } from '@/lib/types'
import { coverage, loaded, widget } from '@/test/samples'

import { Chart } from './chart'
import { chartSpec } from './spec'

/** Yearly totals with an integer year, as an aggregate transform returns them. */
const totals: WidgetData = coverage({
  columns: [
    { name: 'year', type: 'integer' },
    { name: 'region', type: 'text' },
    { name: 'cases', type: 'integer' },
  ],
  rows: [
    [2022, 'North', 11970],
    [2023, 'North', 12511],
    [2024, 'North', 13316],
  ],
})

const lineWithTarget = {
  layer: [
    {
      mark: 'line',
      encoding: { x: { field: 'year', type: 'quantitative' }, y: { field: 'cases', type: 'quantitative' } },
    },
    { mark: { type: 'rule', strokeDash: [4, 4] }, encoding: { y: { datum: 13000 } } },
  ],
}

const barsWithLabels = {
  encoding: {
    x: { field: 'region', type: 'nominal' },
    y: { field: 'coverage', type: 'quantitative', aggregate: 'max' },
  },
  layer: [
    { mark: 'bar' },
    { mark: { type: 'text', dy: -4 }, encoding: { text: { field: 'coverage', aggregate: 'max', format: '.1f' } } },
  ],
}

/** jsdom lays nothing out, so a frame-filling view would be 0 px wide and draw no ticks. */
const sized = (spec: Record<string, unknown>) => ({ ...spec, width: 300, height: 200 })

function svgText(container: HTMLElement): string[] {
  return [...container.querySelectorAll('svg text')].map((text) => text.textContent ?? '')
}

test('puts the rows in as values, fills the frame and writes years without separators', () => {
  const spec = chartSpec(loaded({ widget: widget({ type: 'chart', spec: lineWithTarget }), data: totals, roles: {} }))
  expect(spec.data).toEqual({
    values: [
      { year: 2022, region: 'North', cases: 11970 },
      { year: 2023, region: 'North', cases: 12511 },
      { year: 2024, region: 'North', cases: 13316 },
    ],
  })
  expect(spec).toMatchObject({ width: 'container', height: 'container', autosize: { type: 'fit' } })
  expect(spec.layer).toMatchObject([{ encoding: { x: { axis: { format: 'd' } } } }, {}])

  // A composed view sizes its parts itself.
  const both = chartSpec(loaded({ widget: widget({ spec: { hconcat: [lineWithTarget, lineWithTarget] } }), data: totals }))
  expect(both).not.toHaveProperty('width')
})

test('renders a layered line with its target, and bars with labels, from the injected rows', async () => {
  // As under the frame's CSP without unsafe-eval: no code is generated from strings.
  const real = globalThis.Function
  const generated: unknown[] = []
  const guarded = new Proxy(real, {
    apply: (_target, _this, args) => {
      generated.push(args)
      throw new EvalError('no unsafe-eval')
    },
    construct: (_target, args) => {
      generated.push(args)
      throw new EvalError('no unsafe-eval')
    },
  })
  vi.stubGlobal('Function', guarded)
  const { container, unmount } = render(
    <Chart {...loaded({ widget: widget({ type: 'chart', spec: sized(lineWithTarget) }), data: totals, roles: {} })} />,
  )
  await waitFor(() => expect(container.querySelector('svg')).toBeInTheDocument())
  expect(screen.getByRole('figure', { name: 'Screening coverage' })).toBeInTheDocument()
  await waitFor(() => expect(svgText(container)).toContain('2022'))
  expect(svgText(container)).not.toContain('2,022')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  unmount()

  const bars = render(<Chart {...loaded({ widget: widget({ type: 'chart', spec: sized(barsWithLabels) }) })} />)
  await waitFor(() => expect(svgText(bars.container)).toEqual(expect.arrayContaining(['North', 'South', '72.5'])))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(generated).toEqual([])
})

test('says when a spec does not render', async () => {
  render(<Chart {...loaded({ widget: widget({ type: 'chart', spec: { mark: 'nonsense' } }) })} />)
  expect(await screen.findByRole('alert')).toHaveTextContent('does not render')
})
