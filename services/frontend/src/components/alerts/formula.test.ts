import { expect, test } from 'vitest'

import type { Column } from '@/lib/api'

import {
  addOperand,
  blank,
  canRemove,
  changeKind,
  describe,
  idFactory,
  move,
  nodeIdOf,
  remove,
  unwrap,
  wrap,
  type FormulaNode,
} from './formula'

const columns: Column[] = [
  { name: 'region', type: 'text', nullable: true },
  { name: 'value', type: 'number', nullable: true },
]

const value = (id: string): FormulaNode => ({ id, kind: 'column', column: 'value' })
const constant = (id: string, v: number): FormulaNode => ({ id, kind: 'constant', value: v })
const below = (id: string, v: number): FormulaNode => ({
  id,
  kind: 'compare',
  op: '<',
  args: [value(`${id}-v`), constant(`${id}-c`, v)],
})

test('describes a condition as the server does, and reads the node a server error names', () => {
  const drop: FormulaNode = {
    id: 'drop',
    kind: 'compare',
    op: '<=',
    args: [{ id: 'chg', kind: 'change', periods: 2, args: [value('v')] }, constant('c', -5)],
  }
  expect(describe({ id: 'or', kind: 'or', args: [below('low', 80), drop] })).toBe(
    'value < 80 or change(value, 2 periods) <= -5',
  )
  const nested: FormulaNode = {
    id: 'lt',
    kind: 'compare',
    op: '<',
    args: [
      { id: 'times', kind: 'arithmetic', op: '*', args: [{ id: 'plus', kind: 'arithmetic', op: '+', args: [value('v'), constant('one', 1)] }, constant('two', 2)] },
      constant('three', 3),
    ],
  }
  expect(describe(nested)).toBe('(value + 1) * 2 < 3')
  expect(describe({ id: 'n', kind: 'not', args: [below('low', 80)] })).toBe('not (value < 80)')
  expect(describe({ id: 'd', kind: 'constant', value: '2024-01-01', type: 'date' })).toBe('date 2024-01-01')
  expect(describe({ id: 't', kind: 'constant', value: 'north' })).toBe('"north"')

  expect(nodeIdOf("Formula node 'n3': 'x' is not a column")).toBe('n3')
  expect(nodeIdOf('The key column x is not a column')).toBeNull()
  expect(nodeIdOf(null)).toBeNull()
})

test('operands of and/or are added with new ids, reordered and removed', () => {
  const next = idFactory({ id: 'n1', kind: 'and', args: [below('n2', 1), below('n4', 2)] })
  expect([next(), next()]).toEqual(['n3', 'n5'])
  expect(blank('compare', columns, idFactory(null), 'root')).toEqual({
    id: 'root',
    kind: 'compare',
    op: '<',
    args: [
      { id: 'n1', kind: 'column', column: 'value' },
      { id: 'n2', kind: 'constant', value: 0 },
    ],
  })

  let tree: FormulaNode = { id: 'all', kind: 'and', args: [below('a', 1), below('b', 2)] }
  tree = addOperand(tree, 'all', columns)
  expect(tree.args?.map((arg) => arg.kind)).toEqual(['compare', 'compare', 'compare'])
  const added = tree.args![2].id
  tree = move(tree, added, -1)
  expect(tree.args?.map((arg) => arg.id)).toEqual(['a', added, 'b'])
  // Already first: nothing moves.
  expect(move(tree, 'a', -1)).toBe(tree)

  expect(canRemove(tree, 'a')).toBe(true)
  expect(canRemove(tree, 'a-v')).toBe(false)
  tree = remove(tree, added)
  expect(tree.args?.map((arg) => arg.id)).toEqual(['a', 'b'])
  // With one operand left, the and becomes it.
  expect(remove(tree, 'a')).toEqual(below('b', 2))
})

test('nodes are nested and unwrapped again; changing a kind keeps the id and related operands', () => {
  const low = below('low', 80)
  const negated = wrap(low, 'low', 'not', columns)
  expect(negated.kind).toBe('not')
  expect(negated.args).toEqual([low])
  expect(unwrap(negated, negated.id)).toEqual(low)

  const either = wrap(low, 'low', 'or', columns)
  expect(either.args?.[0]).toEqual(low)
  expect(either.args?.[1].kind).toBe('compare')

  const previous = wrap(low, 'low-v', 'previous', columns)
  expect(describe(previous)).toBe('previous(value, 1 period) < 80')

  const tree: FormulaNode = { id: 'all', kind: 'and', args: [below('a', 1), below('b', 2), below('c', 3)] }
  const any = changeKind(tree, 'all', 'or', columns)
  expect(any.id).toBe('all')
  expect(any.args?.map((arg) => arg.id)).toEqual(['a', 'b', 'c'])

  const arithmetic = changeKind(below('x', 1), 'x', 'arithmetic', columns)
  expect(arithmetic.args?.map((arg) => arg.id)).toEqual(['x-v', 'x-c'])

  // Unrelated: a comparison's sides are no conditions for an and.
  const both = changeKind(below('x', 1), 'x', 'and', columns)
  expect(both.args?.every((arg) => arg.kind === 'compare')).toBe(true)
  expect(both.id).toBe('x')
})
