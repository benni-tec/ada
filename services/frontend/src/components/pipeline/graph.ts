import type { Operator, OperatorId } from '@/lib/api'

export const NODE_WIDTH = 188
export const NODE_HEIGHT = 56
const GAP_X = 72
const GAP_Y = 20
const PAD = 16

export type GraphNode = {
  operator: Operator
  /** Its column: 0 for operators without inputs (sources), then one more than the deepest
   * of its inputs, so every edge points to the right. */
  layer: number
  /** Its place in the column, from the top. */
  row: number
  x: number
  y: number
}

export type GraphEdge = { from: OperatorId; to: OperatorId; path: string }

export type Graph = {
  /** By column, then from the top: the order a keyboard visits them in. */
  nodes: GraphNode[]
  edges: GraphEdge[]
  width: number
  height: number
}

/**
 * Lays a pipeline out left to right by depth: sources at the left, the widget's operator at
 * the right, an edge from each input to every operator that reads it. An operator that
 * several others read (a diamond) is one node with several edges, since the lineage lists
 * each operator once.
 *
 * Within a column, operators are ordered by where their inputs sit (the mean of their rows),
 * which keeps edges from crossing in the pipelines agents build; ties keep the lineage's
 * order.
 */
export function layoutGraph(operators: readonly Operator[]): Graph {
  const byId = new Map(operators.map((operator) => [operator.id, operator]))
  const inputsOf = (operator: Operator) => [...new Set(operator.inputs)].filter((id) => byId.has(id))

  const layers = new Map<OperatorId, number>()
  const layerOf = (operator: Operator): number => {
    const known = layers.get(operator.id)
    if (known !== undefined) return known
    // Operators are immutable and name their inputs by identity, so there are no cycles.
    const inputs = inputsOf(operator).map((id) => layerOf(byId.get(id)!))
    const layer = inputs.length === 0 ? 0 : Math.max(...inputs) + 1
    layers.set(operator.id, layer)
    return layer
  }

  const columns: Operator[][] = []
  for (const operator of operators) (columns[layerOf(operator)] ??= []).push(operator)

  const rows = new Map<OperatorId, number>()
  columns.forEach((column, layer) => {
    const placed =
      layer === 0
        ? column
        : column
            .map((operator, order) => {
              const above = inputsOf(operator).map((id) => rows.get(id) ?? 0)
              const mean = above.length ? above.reduce((sum, row) => sum + row, 0) / above.length : 0
              return { operator, mean, order }
            })
            .sort((a, b) => a.mean - b.mean || a.order - b.order)
            .map(({ operator }) => operator)
    placed.forEach((operator, row) => rows.set(operator.id, row))
    columns[layer] = placed
  })

  const tallest = Math.max(1, ...columns.map((column) => column.length))
  const step = NODE_HEIGHT + GAP_Y
  const nodes: GraphNode[] = columns.flatMap((column, layer) => {
    // Each column is centred against the tallest.
    const offset = ((tallest - column.length) * step) / 2
    return column.map((operator, row) => ({
      operator,
      layer,
      row,
      x: PAD + layer * (NODE_WIDTH + GAP_X),
      y: PAD + offset + row * step,
    }))
  })

  const at = new Map(nodes.map((node) => [node.operator.id, node]))
  const edges = nodes.flatMap(({ operator }) =>
    inputsOf(operator).map((input) => ({ from: input, to: operator.id, path: curve(at.get(input)!, at.get(operator.id)!) })),
  )

  return {
    nodes,
    edges,
    width: PAD * 2 + columns.length * NODE_WIDTH + Math.max(0, columns.length - 1) * GAP_X,
    height: PAD * 2 + tallest * NODE_HEIGHT + (tallest - 1) * GAP_Y,
  }
}

/** From the right edge of one node to the left edge of the next, as a smooth S. */
function curve(from: GraphNode, to: GraphNode): string {
  const [x1, y1] = [from.x + NODE_WIDTH, from.y + NODE_HEIGHT / 2]
  const [x2, y2] = [to.x, to.y + NODE_HEIGHT / 2]
  const middle = (x1 + x2) / 2
  return `M ${x1} ${y1} C ${middle} ${y1}, ${middle} ${y2}, ${x2} ${y2}`
}
