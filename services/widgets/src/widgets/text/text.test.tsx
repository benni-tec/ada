import { render, screen, within } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import type { WidgetData } from '@/lib/types'
import { coverage, loaded, widget } from '@/test/samples'

import { inputsOf, parse } from './model'
import { Text } from './text'

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

/** A second input: a gap per county, without a time role. */
function gaps(overrides: Partial<WidgetData> = {}): WidgetData {
  return coverage({
    output: { columns: [], roles: {} },
    columns: [
      { name: 'county', type: 'text' },
      { name: 'gap', type: 'number' },
      { name: 'cases', type: 'integer' },
      { name: 'year', type: 'integer' },
    ],
    rows: [
      ['Kainuu', 13.26, 13316, 2024],
      ['Lappi', -2.04, 870, 2024],
    ],
    ...overrides,
  })
}

/** Answers the data requests of the inputs other than main. */
function serve(inputs: Record<string, WidgetData | number> = { gap: gaps() }) {
  const fetch = vi.fn(async (request: RequestInfo | URL) => {
    const url = new URL(String(request), 'http://ada.test')
    const answer = inputs[url.searchParams.get('input') ?? 'main']
    if (answer === undefined) return json({ detail: 'Widget w1 has no input' }, 422)
    return typeof answer === 'number' ? json({ detail: 'It broke' }, answer) : json(answer)
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

function show(markdown: string) {
  return render(<Text {...loaded({ widget: widget({ type: 'text', spec: { markdown } }) })} />)
}

const placeholder = (name: string | RegExp) => screen.getByTitle((title) => (typeof name === 'string' ? title.includes(name) : name.test(title)))

afterEach(() => {
  Object.defineProperty(window, 'parent', { value: window, configurable: true })
})

test('reads the placeholders: values, formats, rows, whole inputs, and escapes', () => {
  const pieces = parse(
    'A {{gap.gap:percent}} b {{main.coverage[region=South][year=2024]:integer}} {{gap}} \\{{gap.gap}} {{ not one }}',
  )
  expect(pieces).toEqual([
    'A ',
    { source: '{{gap.gap:percent}}', input: 'gap', column: 'gap', where: [], format: 'percent' },
    ' b ',
    {
      source: '{{main.coverage[region=South][year=2024]:integer}}',
      input: 'main',
      column: 'coverage',
      where: [
        { column: 'region', value: 'South' },
        { column: 'year', value: '2024' },
      ],
      format: 'integer',
    },
    ' ',
    { source: '{{gap}}', input: 'gap', where: [] },
    ' \\{{gap.gap}} {{ not one }}',
  ])
  expect(inputsOf(pieces)).toEqual(['gap', 'main'])
})

test('shows values of two inputs, all read in the run main was read in', async () => {
  const fetch = serve()
  show('South reached {{main.coverage[region=South]}} %, and Kainuu’s gap is {{gap.gap[county=Kainuu]}}.')

  expect(await screen.findByText('13.26')).toBeInTheDocument()
  // The latest period of the time role.
  expect(screen.getByText('72.5')).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(fetch).toHaveBeenCalledWith('/api/widgets/w1/data?limit=1000&run_id=r1&input=gap')
  // Where each value comes from, in its tooltip.
  const gap = placeholder('Input: gap')
  expect(gap.title).toContain('Column: gap')
  expect(gap.title).toContain('Row: county = Kainuu')
  expect(gap.title).toContain('Run: r1')
  expect(gap.title).toMatch(/Fetched: /)
})

test('writes a value in each format', async () => {
  serve()
  const count = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 })
  show(
    [
      '{{gap.cases[county=Kainuu]:integer}}',
      '{{gap.gap[county=Kainuu]:number1}}',
      '{{gap.gap[county=Kainuu]:percent}}',
      '{{gap.cases[county=Kainuu]:plain}}',
      '{{gap.gap[county=Kainuu]:signed1}}',
      '{{gap.gap[county=Lappi]:signed1}}',
      '{{gap.year[county=Lappi]}}',
    ].join(' | '),
  )
  await screen.findByText(count.format(13316))
  expect(screen.getByText('13.3')).toBeInTheDocument()
  expect(screen.getByText('13.3 %')).toBeInTheDocument()
  expect(screen.getByText('13316')).toBeInTheDocument()
  expect(screen.getByText('+13.3')).toBeInTheDocument()
  expect(screen.getByText('−2.0')).toBeInTheDocument()
  // A year is written without a separator.
  expect(screen.getByText('2024')).toBeInTheDocument()
})

test('marks the values of a stale or simulated input, as the runtime marks the widget', async () => {
  serve({ gap: gaps({ is_stale: true }) })
  show('Fresh {{main.coverage[region=North]}}, stale {{gap.gap[county=Lappi]}}.')

  const stale = await screen.findByTitle((title) => title.includes('Input: gap'))
  expect(within(stale).getByText('stale')).toHaveClass('ada-flag-stale')
  expect(stale.title).toContain('Stale: last good data')
  expect(within(placeholder('Input: main')).queryByText('stale')).not.toBeInTheDocument()
  // Main is not stale, so the runtime says nothing: the widget says it once at the top.
  expect(screen.getByRole('list', { name: 'Data warnings' })).toHaveTextContent('Stale')
})

test('shows "no value" with the reason, never a blank', async () => {
  serve({ gap: gaps(), broken: 500 })
  show(
    [
      '{{gap.gap[county=Uusimaa]}}',
      '{{gap.deaths[county=Kainuu]}}',
      '{{gap.gap}}',
      '{{main.coverage}}',
      '{{gap.county[county=Kainuu]:percent}}',
      '{{broken.value}}',
    ].join(' / '),
  )
  await screen.findAllByText('no value')
  const reasons = screen.getAllByText('no value').map((element) => element.getAttribute('title')!.split('\n')[0])
  expect(reasons).toEqual([
    'The input "gap" has no row where county = Uusimaa',
    'The input "gap" has no column "deaths"',
    'The input "gap" has 2 rows, and a value needs one: pick it with [column=value]',
    'The input "main" has 2 rows in the latest period, and a value needs one: pick it with [column=value]',
    'The format percent needs a number; "county" is text',
    'The input "broken" cannot be read: It broke',
  ])
})

test('shows a whole input as a compact table, at most 50 rows', async () => {
  const rows = Array.from({ length: 60 }, (_, index) => [`County ${index}`, index, index, 2024])
  serve({ gap: gaps({ rows }) })
  show('Gaps:\n\n{{gap}}\n\nThat is all.')

  const table = await screen.findByRole('table')
  expect(within(table).getAllByRole('row')).toHaveLength(51)
  expect(screen.getByText('Input gap: the first 50 rows')).toBeInTheDocument()
  // Not inside a paragraph.
  expect(table.closest('p')).toBeNull()
})

test('renders no raw HTML and no images, and opens links in a new tab', () => {
  const { container } = show(
    'Hi <b>bold</b> <script>alert(1)</script> <img src="https://x.test/a.png"> ![chart](https://x.test/b.png) [docs](https://example.org) [bad](javascript:alert(1))',
  )
  expect(container.querySelector('b, script, img, iframe')).toBeNull()
  const link = screen.getByRole('link', { name: 'docs' })
  expect(link).toHaveAttribute('target', '_blank')
  expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  expect(container.querySelector('a[href^="javascript"]')).toBeNull()
})

test('an escaped placeholder and placeholders in code stay as written; values are text, never Markdown', async () => {
  serve({ gap: gaps({ rows: [['<b>*Kainuu*</b>', 1, 1, 2024]] }) })
  const { container } = show('Write \\{{gap.gap}} for a value: `{{gap.gap}}`. The county is {{gap.county}}.')
  expect(await screen.findByText('<b>*Kainuu*</b>')).toBeInTheDocument()
  expect(container.querySelector('b, em')).toBeNull()
  expect(container.querySelector('p')).toHaveTextContent('Write {{gap.gap}} for a value: {{gap.gap}}.')
})

test('a click on a value asks the page to open that input’s pipeline', async () => {
  serve()
  window.location.hash = '#widget=w1&run=r1'
  const parent = { postMessage: vi.fn() }
  Object.defineProperty(window, 'parent', { value: parent, configurable: true })
  show('Gap {{gap.gap[county=Kainuu]}}')

  ;(await screen.findByRole('button', { name: /13.26/ })).click()
  expect(parent.postMessage).toHaveBeenCalledWith({ type: 'ada:open-pipeline', input: 'gap' }, '*')
})
