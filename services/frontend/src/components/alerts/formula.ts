// The formula tree of an alert rule, as the server takes it (docs/contracts.md, "Alerts"),
// and the edits the builder makes to it. Every edit returns a new tree; ids never change, so
// a server error that names a node keeps pointing at the same node while it is edited.

import type { Column } from '@/lib/api'

export type NodeKind =
  | 'column'
  | 'constant'
  | 'arithmetic'
  | 'compare'
  | 'and'
  | 'or'
  | 'not'
  | 'previous'
  | 'change'
  | 'rolling_mean'

export type ConstantType = 'date' | 'timestamp'

export type FormulaNode = {
  id: string
  kind: NodeKind
  column?: string
  value?: string | number | boolean
  type?: ConstantType
  op?: string
  periods?: number
  args?: FormulaNode[]
}

export const kindLabels: Record<NodeKind, string> = {
  compare: 'Comparison',
  and: 'All of (and)',
  or: 'Any of (or)',
  not: 'Not',
  column: 'Column',
  constant: 'Constant',
  arithmetic: 'Arithmetic',
  previous: 'Previous period',
  change: 'Change over periods',
  rolling_mean: 'Rolling mean',
}

export const arithmeticOps = ['+', '-', '*', '/'] as const
export const compareOps = ['<', '<=', '>', '>=', '=', '!='] as const
export const timeKinds: readonly NodeKind[] = ['previous', 'change', 'rolling_mean']
/** Kinds whose operands may be added and removed freely. */
const variadic: readonly NodeKind[] = ['and', 'or']

/** The node a server error names, from its `Formula node '<id>': …` detail. */
export function nodeIdOf(message: string | null | undefined): string | null {
  const match = /^Formula node '([^']+)'/.exec(message ?? '')
  return match ? match[1] : null
}

function ids(node: FormulaNode, into = new Set<string>()): Set<string> {
  into.add(node.id)
  for (const arg of node.args ?? []) ids(arg, into)
  return into
}

/** A fresh id, unique in the tree: n1, n2, … */
export function idFactory(tree: FormulaNode | null): () => string {
  const taken = tree ? ids(tree) : new Set<string>()
  let next = 1
  return () => {
    while (taken.has(`n${next}`)) next++
    const id = `n${next}`
    taken.add(id)
    return id
  }
}

function firstColumn(columns: readonly Column[]): string {
  const numeric = columns.find((column) => column.type === 'number' || column.type === 'integer')
  return (numeric ?? columns[0])?.name ?? ''
}

/** A node of `kind` with sensible operands, so the tree stays valid where it can. */
export function blank(kind: NodeKind, columns: readonly Column[], newId: () => string, id = newId()): FormulaNode {
  const column = (): FormulaNode => ({ id: newId(), kind: 'column', column: firstColumn(columns) })
  const constant = (value = 0): FormulaNode => ({ id: newId(), kind: 'constant', value })
  const comparison = (): FormulaNode => ({ id: newId(), kind: 'compare', op: '<', args: [column(), constant()] })
  switch (kind) {
    case 'column':
      return { id, kind, column: firstColumn(columns) }
    case 'constant':
      return { id, kind, value: 0 }
    case 'arithmetic':
      return { id, kind, op: '-', args: [column(), constant()] }
    case 'compare':
      return { id, kind, op: '<', args: [column(), constant()] }
    case 'and':
    case 'or':
      return { id, kind, args: [comparison(), comparison()] }
    case 'not':
      return { id, kind, args: [comparison()] }
    case 'previous':
    case 'change':
      return { id, kind, periods: 1, args: [column()] }
    case 'rolling_mean':
      return { id, kind, periods: 3, args: [column()] }
  }
}

/** The tree with the node `id` replaced by what `change` makes of it. */
export function replace(tree: FormulaNode, id: string, change: (node: FormulaNode) => FormulaNode): FormulaNode {
  if (tree.id === id) return change(tree)
  if (!tree.args) return tree
  return { ...tree, args: tree.args.map((arg) => replace(arg, id, change)) }
}

/** The parent of the node `id`, and its position among the parent's operands. */
export function parentOf(tree: FormulaNode, id: string): { parent: FormulaNode; index: number } | null {
  for (const [index, arg] of (tree.args ?? []).entries()) {
    if (arg.id === id) return { parent: tree, index }
    const found = parentOf(arg, id)
    if (found) return found
  }
  return null
}

/** Moves a node one place earlier (-1) or later (+1) among its siblings. */
export function move(tree: FormulaNode, id: string, delta: -1 | 1): FormulaNode {
  const found = parentOf(tree, id)
  if (!found) return tree
  const { parent, index } = found
  const target = index + delta
  const args = [...(parent.args ?? [])]
  if (target < 0 || target >= args.length) return tree
  ;[args[index], args[target]] = [args[target], args[index]]
  return replace(tree, parent.id, (node) => ({ ...node, args }))
}

/** Whether `remove` can take the node out: only an operand of and/or can go. */
export function canRemove(tree: FormulaNode, id: string): boolean {
  const found = parentOf(tree, id)
  return found !== null && variadic.includes(found.parent.kind)
}

/** Takes an operand out of and/or; with one operand left, the and/or becomes that operand. */
export function remove(tree: FormulaNode, id: string): FormulaNode {
  const found = parentOf(tree, id)
  if (!found || !variadic.includes(found.parent.kind)) return tree
  const rest = (found.parent.args ?? []).filter((arg) => arg.id !== id)
  return replace(tree, found.parent.id, (node) => (rest.length === 1 ? rest[0] : { ...node, args: rest }))
}

/** Whether the node has an operand that can take its place. */
export function canUnwrap(node: FormulaNode): boolean {
  return (node.args?.length ?? 0) > 0
}

/** Replaces the node by its first operand, e.g. not(x) by x. */
export function unwrap(tree: FormulaNode, id: string): FormulaNode {
  return replace(tree, id, (node) => node.args?.[0] ?? node)
}

/** Nests the node inside a new node of `kind`, as its first operand. */
export function wrap(tree: FormulaNode, id: string, kind: NodeKind, columns: readonly Column[]): FormulaNode {
  const newId = idFactory(tree)
  return replace(tree, id, (node) => {
    const outer = blank(kind, columns, newId)
    const args = outer.args ?? []
    return { ...outer, args: [node, ...args.slice(1)] }
  })
}

/** Adds a comparison to an and/or. */
export function addOperand(tree: FormulaNode, id: string, columns: readonly Column[]): FormulaNode {
  const newId = idFactory(tree)
  return replace(tree, id, (node) => ({ ...node, args: [...(node.args ?? []), blank('compare', columns, newId)] }))
}

/** Kinds whose operands mean the same sort of thing, so a change between them keeps them. */
const families: readonly (readonly NodeKind[])[] = [
  ['and', 'or', 'not'],
  ['compare', 'arithmetic'],
  ['previous', 'change', 'rolling_mean'],
]

function sameFamily(a: NodeKind, b: NodeKind): boolean {
  return families.some((family) => family.includes(a) && family.includes(b))
}

/** Changes a node's kind, keeping its id; operands of a related kind are kept. */
export function changeKind(tree: FormulaNode, id: string, kind: NodeKind, columns: readonly Column[]): FormulaNode {
  const newId = idFactory(tree)
  return replace(tree, id, (node) => {
    const fresh = blank(kind, columns, newId, node.id)
    const kept = sameFamily(kind, node.kind) ? (node.args ?? []) : []
    if (!fresh.args) return fresh
    // E.g. and → or keeps both conditions; compare → arithmetic keeps both sides.
    const args = fresh.args.map((arg, index) => kept[index] ?? arg)
    const extra = variadic.includes(kind) && variadic.includes(node.kind) ? kept.slice(args.length) : []
    return { ...fresh, args: [...args, ...extra] }
  })
}

// The text form, the same as the server's (formula.py): only the parentheses the meaning
// needs.

const precedence: Record<string, number> = { or: 1, and: 2, not: 3, compare: 4, '+': 5, '-': 5, '*': 6, '/': 6 }
const atom = 7

function precedenceOf(node: FormulaNode): number {
  if (node.kind === 'arithmetic') return precedence[node.op ?? '+'] ?? atom
  return precedence[node.kind] ?? atom
}

function operand(node: FormulaNode, parent: number, right: boolean): string {
  const text = describe(node)
  const own = precedenceOf(node)
  const tie = right && own === parent && node.kind !== 'and' && node.kind !== 'or'
  return own < parent || tie ? `(${text})` : text
}

/** The condition as a person reads it, e.g. `value < 80 or change(value, 1 period) <= -5`. */
export function describe(node: FormulaNode): string {
  const args = node.args ?? []
  switch (node.kind) {
    case 'column':
      return /^[A-Za-z_][A-Za-z0-9_]*$/.test(node.column ?? '') ? (node.column ?? '') : `[${node.column ?? ''}]`
    case 'constant':
      if (node.type) return `${node.type} ${String(node.value ?? '')}`
      return typeof node.value === 'string' ? JSON.stringify(node.value) : String(node.value ?? '')
    case 'previous':
    case 'change':
    case 'rolling_mean': {
      const periods = node.periods ?? 1
      const inner = args[0] ? describe(args[0]) : '?'
      return `${node.kind}(${inner}, ${periods === 1 ? '1 period' : `${periods} periods`})`
    }
    case 'not':
      // Anything but a single value is parenthesised: not (a < b) reads unambiguously.
      return `not ${args[0] ? operand(args[0], atom, false) : '?'}`
    default: {
      const own = precedenceOf(node)
      const joiner = node.kind === 'and' || node.kind === 'or' ? ` ${node.kind} ` : ` ${node.op ?? '?'} `
      return args.map((arg, index) => operand(arg, own, index > 0)).join(joiner)
    }
  }
}

/** A formula from the server, typed for the builder. The server checked its shape. */
export function asFormula(value: unknown): FormulaNode {
  return value as FormulaNode
}
