import { expect, test } from 'vitest'

import type { Operator } from '@/lib/api'

import { layoutGraph, NODE_HEIGHT, NODE_WIDTH } from './graph'
import { columnRoles, sqlHeadline } from './labels'

function operator(id: string, kind: Operator['kind'], inputs: string[] = [], params: Record<string, unknown> = {}): Operator {
  return {
    id,
    project_id: 'p1',
    kind,
    params,
    inputs,
    output: { kind: 'table', columns: [], roles: { measures: [] }, derived: false },
    materializing: kind === 'source',
    created_by: { kind: 'user', name: 'web' },
    created_at: '2026-11-01T09:00:00Z',
  } as Operator
}

// A diamond: the screening source is read by a join and by an input slot, and the
// widget's operator reads both.
const screening = operator('op_s', 'source', [], { data_source_id: 'ds1' })
const regions = operator('op_r', 'source', [], { data_source_id: 'ds2' })
const join = operator('op_j', 'transform', ['op_s', 'op_r'], { sql: 'SELECT * FROM input_0 JOIN input_1 USING (region)' })
const slot = operator('op_i', 'input', ['op_s'], { name: 'screening' })
const map = operator('op_t', 'transform', ['op_j', 'op_i'], { sql: '-- Latest year per county\nSELECT 1' })
const lineage = [screening, regions, join, slot, map]

test('lays operators out by depth, sources at the left, and draws a shared input once', () => {
  const graph = layoutGraph(lineage)
  const layer = Object.fromEntries(graph.nodes.map((node) => [node.operator.id, node.layer]))
  expect(layer).toEqual({ op_s: 0, op_r: 0, op_j: 1, op_i: 1, op_t: 2 })

  const at = new Map(graph.nodes.map((node) => [node.operator.id, node]))
  expect(at.get('op_s')!.x).toBe(at.get('op_r')!.x)
  expect(at.get('op_j')!.x).toBeGreaterThan(at.get('op_s')!.x + NODE_WIDTH)
  expect(at.get('op_t')!.x).toBeGreaterThan(at.get('op_j')!.x + NODE_WIDTH)
  // A column of one sits in the middle of the columns of two.
  expect(at.get('op_t')!.y).toBe((at.get('op_j')!.y + at.get('op_i')!.y) / 2)
  // The whole graph fits its box.
  for (const node of graph.nodes) {
    expect(node.x + NODE_WIDTH).toBeLessThanOrEqual(graph.width)
    expect(node.y + NODE_HEIGHT).toBeLessThanOrEqual(graph.height)
  }

  expect(graph.nodes.filter((node) => node.operator.id === 'op_s')).toHaveLength(1)
  expect(graph.edges.map((edge) => `${edge.from}->${edge.to}`).sort()).toEqual([
    'op_i->op_t',
    'op_j->op_t',
    'op_r->op_j',
    'op_s->op_i',
    'op_s->op_j',
  ])
  // From the right edge of the input to the left edge of its reader.
  const edge = graph.edges.find((candidate) => candidate.from === 'op_r')!
  const from = graph.nodes.find((node) => node.operator.id === 'op_r')!
  const to = graph.nodes.find((node) => node.operator.id === 'op_j')!
  expect(edge.path.startsWith(`M ${from.x + NODE_WIDTH} ${from.y + NODE_HEIGHT / 2}`)).toBe(true)
  expect(edge.path.endsWith(`${to.x} ${to.y + NODE_HEIGHT / 2}`)).toBe(true)
})

test('an input read twice is one edge, inputs outside the lineage are ignored, and a column follows its inputs', () => {
  const self = operator('op_x', 'transform', ['op_s', 'op_s', 'op_gone'], { sql: 'SELECT 1' })
  const graph = layoutGraph([screening, self])
  expect(graph.edges.map((edge) => `${edge.from}->${edge.to}`)).toEqual(['op_s->op_x'])

  const a = operator('op_a', 'source')
  const b = operator('op_b', 'source')
  // Listed in the opposite order of their inputs.
  const fromB = operator('op_fb', 'transform', ['op_b'])
  const fromA = operator('op_fa', 'transform', ['op_a'])
  const ordered = layoutGraph([a, b, fromB, fromA])
  const row = Object.fromEntries(ordered.nodes.map((node) => [node.operator.id, node.row]))
  expect(row).toMatchObject({ op_a: 0, op_b: 1, op_fa: 0, op_fb: 1 })
})

test('names a query by its leading comment, and each column by its roles', () => {
  expect(sqlHeadline('-- Latest year per county\nSELECT 1')).toBe('Latest year per county')
  expect(sqlHeadline('SELECT b.county_code, b.name, d.value FROM input_2 AS b LEFT JOIN input_0')).toBe(
    'SELECT b.county_code, b.name,…',
  )
  expect(sqlHeadline('/* note */ SELECT   *\n FROM input_0')).toBe('SELECT * FROM input_0')

  const roles = columnRoles({
    time: { start: 'period_start', end: 'period_end', grain: 'year' },
    geo: { code: 'county_code', system: 'statfin', level: 'wellbeing_services_county' },
    measures: [{ value: 'value', lower: 'low', upper: 'high', suppressed: null, coverage: null }],
  })
  expect(Object.fromEntries(roles)).toEqual({
    period_start: ['Time: period start (year)'],
    period_end: ['Time: period end (year)'],
    county_code: ['Geography: statfin, wellbeing services county'],
    value: ['Measure'],
    low: ['Lower bound of value'],
    high: ['Upper bound of value'],
  })
})
