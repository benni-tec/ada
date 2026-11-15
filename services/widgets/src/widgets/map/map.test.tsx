import { fireEvent, render, screen, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import { latestPerKey } from '@/lib/columns'
import type { Loaded } from '@/lib/runtime'
import type { Roles, WidgetData } from '@/lib/types'
import { loaded, widget } from '@/test/samples'

import { RegionMap } from './map'
import { anchorOf, buildMap, classes, parseGeometry, placeLabels, shortNames, type MapModel, type Region } from './model'

/** A square in planar metres, as Statistics Finland's boundaries come (EPSG:3067). */
function square(x: number, y: number, size = 100_000) {
  return JSON.stringify({
    type: 'Polygon',
    coordinates: [
      [
        [x, y],
        [x + size, y],
        [x + size, y + size],
        [x, y + size],
        [x, y],
      ],
    ],
  })
}

const roles: Roles = {
  time: { start: 'period_start', end: 'period_end', grain: 'year' },
  geo: { code: 'county_code', system: 'statfin', level: 'wellbeing_services_county' },
  measures: [{ value: 'share', lower: 'share_low', upper: 'share_high', suppressed: 'hidden' }],
}

/** Screening by county over two years: Helsinki changes, Lapland is suppressed in the
 * latest year, Åland has no value at all. */
function counties(overrides: Partial<WidgetData> = {}): WidgetData {
  return {
    widget_id: 'w1',
    run_id: 'r1',
    output: { columns: [], roles },
    columns: [
      { name: 'county_code', type: 'text' },
      { name: 'name', type: 'text' },
      { name: 'period_start', type: 'date' },
      { name: 'period_end', type: 'date' },
      { name: 'share', type: 'number' },
      { name: 'share_low', type: 'number' },
      { name: 'share_high', type: 'number' },
      { name: 'hidden', type: 'boolean' },
      { name: 'geometry', type: 'text' },
    ],
    rows: [
      ['90', 'City of Helsinki', '2023-01-01', '2023-12-31', 74, 73, 75, false, square(380_000, 6_670_000)],
      ['90', 'City of Helsinki', '2024-01-01', '2024-12-31', 74.3, 73.8, 74.8, false, square(380_000, 6_670_000)],
      ['19', 'North Ostrobothnia', '2024-01-01', '2024-12-31', 85.6, 85.1, 86.1, false, square(400_000, 7_200_000)],
      ['17', 'Ostrobothnia', '2024-01-01', '2024-12-31', 80, 79, 81, false, square(250_000, 7_000_000)],
      ['21', 'Lapland', '2024-01-01', '2024-12-31', null, null, null, true, square(400_000, 7_500_000)],
      ['91', 'Åland', null, null, null, null, null, null, square(100_000, 6_680_000)],
    ],
    truncated: false,
    is_scenario: false,
    is_stale: false,
    ...overrides,
  }
}

function sample(overrides: Partial<Loaded> = {}): Loaded {
  return loaded({ widget: widget({ type: 'map', title: 'Screening' }), data: counties(), roles, ...overrides })
}

test('takes each region at its latest period and classes the values', () => {
  const model = buildMap(sample()) as MapModel

  expect(model.value).toBe('share')
  expect(model.period).toBe('2024')
  const byCode = Object.fromEntries(model.regions.map((region) => [region.code, region]))
  expect(byCode['90']).toMatchObject({ value: 74.3, lower: 73.8, upper: 74.8, state: 'value', bin: 0 })
  expect(byCode['19']).toMatchObject({ value: 85.6, state: 'value', bin: 4 })
  expect(byCode['17'].bin).toBe(2)
  // Suppressed and missing values are never a class of the scale.
  expect(byCode['21']).toMatchObject({ value: null, state: 'suppressed', bin: null })
  expect(byCode['91']).toMatchObject({ value: null, state: 'missing', bin: null, period: null })
  expect(model.hasMissing && model.hasSuppressed).toBe(true)
  // North is up: North Ostrobothnia lies above Helsinki in the drawing.
  const top = (code: string) => Number(byCode[code].path.split(' ')[1].split('L')[0])
  expect(top('19')).toBeLessThan(top('90'))

  // The helpers underneath.
  expect(parseGeometry('not json')).toBeNull()
  expect(parseGeometry({ type: 'Point', coordinates: [1, 2] })).toBeNull()
  expect(parseGeometry(square(0, 0))?.type).toBe('Polygon')
  expect(classes([1, 1])).toEqual([{ from: 1, to: 1 }])
  expect(classes([0, 10]).map((bin) => bin.to)).toEqual([2, 4, 6, 8, 10])
  const rows = [
    ['a', '2023-12-31'],
    ['a', '2024-12-31'],
    ['a', null],
    ['b', null],
  ]
  expect([...latestPerKey(rows, 0, 1).values()]).toEqual([
    ['a', '2024-12-31'],
    ['b', null],
  ])
})

test('draws every region, a legend and the marks of missing data, and lists the values in a table', () => {
  const { container } = render(<RegionMap {...sample()} />)

  expect(screen.getByRole('img')).toHaveAccessibleName(
    'Screening: Map of share by region, 5 regions, 2024. Use the arrow keys to read each region.',
  )
  expect(container.querySelectorAll('path[data-region]')).toHaveLength(5)
  expect(container.querySelector('[data-region="21"]')).toHaveAttribute('fill', 'url(#ada-map-suppressed)')
  expect(container.querySelector('[data-region="91"]')).toHaveAttribute('fill', 'var(--map-missing)')
  expect(container.querySelector('[data-region="19"]')).toHaveAttribute('fill', 'var(--seq-5)')

  const legend = screen.getByRole('list', { name: 'Legend' })
  expect(within(legend).getAllByRole('listitem')).toHaveLength(5 + 3)
  expect(legend).toHaveTextContent('74.3–76.56')
  expect(legend).toHaveTextContent('No data')
  expect(legend).toHaveTextContent('Suppressed')

  // Every value, in a table for screen readers.
  const table = screen.getByRole('table')
  expect(within(table).getAllByRole('row')).toHaveLength(1 + 5)
  expect(within(table).getByRole('row', { name: /North Ostrobothnia/ })).toHaveTextContent('85.6 (85.1–86.1)2024')
})

test('reads each region with the keyboard', () => {
  render(<RegionMap {...sample()} />)
  const map = screen.getByRole('img')

  // Regions in alphabetical order, as people look them up: Åland sorts with the A.
  fireEvent.keyDown(map, { key: 'ArrowRight' })
  expect(screen.getByRole('status')).toHaveTextContent('Åland')
  expect(screen.getByRole('status')).toHaveTextContent('share: no data')
  fireEvent.keyDown(map, { key: 'ArrowRight' })
  expect(screen.getByRole('status')).toHaveTextContent('City of Helsinkishare: 74.3 (73.8–74.8)')
  fireEvent.keyDown(map, { key: 'ArrowDown' })
  expect(screen.getByRole('status')).toHaveTextContent('Lapland')
  expect(screen.getByRole('status')).toHaveTextContent('share: suppressed')
  // Back past the start wraps to the last region.
  fireEvent.keyDown(map, { key: 'ArrowLeft' })
  fireEvent.keyDown(map, { key: 'ArrowLeft' })
  fireEvent.keyDown(map, { key: 'ArrowUp' })
  expect(screen.getByRole('status')).toHaveTextContent('Ostrobothnia')
  expect(screen.getByRole('status')).not.toHaveTextContent('North')
  fireEvent.keyDown(map, { key: 'Escape' })
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})

test('draws longitude and latitude with north up', () => {
  const lonLat = (lon: number, lat: number) =>
    JSON.stringify({ type: 'MultiPolygon', coordinates: [[[[lon, lat], [lon + 1, lat], [lon + 1, lat + 1], [lon, lat]]]] })
  const data = counties({
    rows: [
      ['01', 'South', '2024-01-01', '2024-12-31', 1, null, null, false, lonLat(24, 60)],
      ['02', 'North', '2024-01-01', '2024-12-31', 2, null, null, false, lonLat(25, 68)],
    ],
  })
  const model = buildMap(sample({ data })) as MapModel

  const [north, south] = model.regions
  expect(north.name).toBe('North')
  expect(model.box[3]).toBe(1000)
  // East-west is shortened by the latitude: the box is taller than wide.
  expect(model.box[2]).toBeLessThan(model.box[3])
  expect(north.path.startsWith('M')).toBe(true)
  expect(south.path).not.toBe('')
})

test('names what is missing to draw a map', () => {
  const { rerender } = render(<RegionMap {...sample({ roles: { ...roles, geo: null } })} />)
  expect(screen.getByRole('alert')).toHaveTextContent('A map needs a geography role')
  rerender(<RegionMap {...sample({ widget: widget({ type: 'map', spec: { geometry: 'shape' } }) })} />)
  expect(screen.getByRole('alert')).toHaveTextContent('No column "shape" with the region outlines')
})

test('every region is named on the map, by its name and value where it fits, else by a number in a key', () => {
  const { container } = render(<RegionMap {...sample()} />)
  const labels = container.querySelector('.ada-map-labels')!
  expect(labels).toHaveAttribute('aria-hidden', 'true')
  // Five regions, each named once: as a label or in the key.
  const named = [...labels.querySelectorAll(':scope > text')].map((text) => text.textContent)
  const key = [...container.querySelectorAll('.ada-map-key li')].map((item) => item.textContent)
  expect(named.length + key.length).toBe(5)
  expect([...named, ...key].join(' ')).toContain('North Ostrobothnia85.6'.slice(0, 18))
})

test('a label goes inside its region: the centroid, or for a crescent the middle of its widest stretch', () => {
  const same = (x: number, y: number) => [x, y]
  const box = { type: 'Polygon' as const, coordinates: [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]] }
  expect(anchorOf(box, same)).toEqual({ anchor: [5, 5], area: 100 })
  // A C open to the east: its centroid falls in the opening.
  const c = { type: 'Polygon' as const, coordinates: [[[0, 0], [10, 0], [10, 2], [2, 2], [2, 8], [10, 8], [10, 10], [0, 10], [0, 0]]] }
  const { anchor } = anchorOf(c, same)
  expect(anchor![0]).toBeLessThan(2)
  // The largest part of a multipolygon is the one labelled.
  const islands = { type: 'MultiPolygon' as const, coordinates: [[[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]], [[[20, 20], [30, 20], [30, 30], [20, 30], [20, 20]]]] }
  expect(anchorOf(islands, same)).toEqual({ anchor: [25, 25], area: 100 })
})

test('names lose the words most of them end with', () => {
  expect(shortNames(['Lapland wellbeing services county', 'Kainuu wellbeing services county', 'City of Helsinki'])).toEqual([
    'Lapland',
    'Kainuu',
    'City of Helsinki',
  ])
  expect(shortNames(['Helsinki', 'Espoo'])).toEqual(['Helsinki', 'Espoo'])
})

test('labels never overlap or cover another region: crowded regions are numbered, and a number in the way moves out with a line', () => {
  const region = (code: string, x: number, y: number, area: number): Region => ({
    code, name: code, path: 'M0 0Z', value: 1, lower: null, upper: null, state: 'value', bin: 0, period: null, anchor: [x, y], area,
  })
  const texts = new Map([['big', ['A long region name']], ['near', ['Another long name']], ['alone', ['Lapland', '83.8']]])
  const labels = placeLabels([region('near', 104, 100, 50), region('big', 100, 100, 500), region('alone', 300, 300, 900)], texts, 10)
  expect(labels.find((l) => l.code === 'alone')).toMatchObject({ x: 300, y: 300, lines: ['Lapland', '83.8'] })
  // Either label would cover the other's region: both numbered, north to south then west
  // to east, and the second moved off the first, a line back to its own region.
  expect(labels.find((l) => l.code === 'big')).toMatchObject({ number: 1, x: 100, y: 100 })
  const near = labels.find((l) => l.code === 'near')!
  expect(near).toMatchObject({ number: 2, from: [104, 100] })
  expect(Math.hypot(near.x - 100, near.y - 100)).toBeGreaterThan(10)
})
