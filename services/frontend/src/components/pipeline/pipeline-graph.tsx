import { useId, useRef, type KeyboardEvent } from 'react'

import type { Operator, OperatorId } from '@/lib/api'

import { layoutGraph, NODE_HEIGHT, NODE_WIDTH, type Graph, type GraphNode } from './graph'
import { kindLabels, shortName, type SourceInfo } from './labels'

// Materializing operators store a snapshot (the evidence); pass-through ones only their
// definition. Solid and tinted against dashed and plain, so it reads without colour too.
const looks = {
  materializing:
    'border-2 border-solid border-teal-600 bg-teal-50 dark:border-teal-400 dark:bg-teal-950',
  passThrough:
    'border-2 border-dashed border-neutral-400 bg-white dark:border-neutral-500 dark:bg-neutral-900',
}

/**
 * The operator tree as a directed graph: edges drawn in SVG, each operator a button laid
 * over them at its place, so the nodes are ordinary focusable controls. Tab visits them
 * column by column, from the sources to the widget's operator; the arrow keys follow the
 * edges (left to an input, right to an operator that reads it) and the columns (up and
 * down), selecting as they go.
 */
export function PipelineGraph({
  operators,
  target,
  selected,
  onSelect,
  sourceOf,
}: {
  operators: readonly Operator[]
  /** The widget's operator. */
  target: OperatorId
  selected: OperatorId
  onSelect: (id: OperatorId) => void
  sourceOf: (operator: Operator) => SourceInfo | undefined
}) {
  const graph = layoutGraph(operators)
  const arrow = useId()
  const legendId = useId()
  const hintId = useId()
  const container = useRef<HTMLDivElement>(null)
  const onKeyDown = (node: GraphNode) => (event: KeyboardEvent<HTMLButtonElement>) => {
    const next = neighbour(graph, node, event.key)
    if (!next) return
    event.preventDefault()
    onSelect(next)
    container.current?.querySelector<HTMLElement>(`[data-operator="${next}"]`)?.focus()
  }
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-auto">
        <div
          ref={container}
          role="group"
          aria-label="Operators, from the sources to the widget"
          aria-describedby={`${hintId} ${legendId}`}
          className="relative"
          style={{ width: graph.width, height: graph.height }}
        >
          <svg
            width={graph.width}
            height={graph.height}
            aria-hidden="true"
            data-testid="pipeline-edges"
            className="absolute inset-0 text-neutral-400 dark:text-neutral-500"
          >
            <defs>
              <marker id={arrow} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
              </marker>
            </defs>
            {graph.edges.map((edge) => (
              <path
                key={`${edge.from}->${edge.to}`}
                d={edge.path}
                data-from={edge.from}
                data-to={edge.to}
                fill="none"
                stroke="currentColor"
                strokeWidth={1.5}
                markerEnd={`url(#${arrow})`}
              />
            ))}
          </svg>
          {graph.nodes.map((node) => {
            const { operator, x, y, layer } = node
            const isSelected = operator.id === selected
            const isTarget = operator.id === target
            const name = shortName(operator, sourceOf(operator))
            return (
              <button
                key={operator.id}
                type="button"
                aria-pressed={isSelected}
                aria-label={`${kindLabels[operator.kind]}: ${name}${operator.materializing ? ', stores a snapshot' : ''}${
                  isTarget ? ', the widget reads this' : ''
                }`}
                data-operator={operator.id}
                data-layer={layer}
                data-x={x}
                data-y={y}
                data-autofocus={isTarget || undefined}
                onClick={() => onSelect(operator.id)}
                onKeyDown={onKeyDown(node)}
                style={{ left: x, top: y, width: NODE_WIDTH, height: NODE_HEIGHT }}
                className={`absolute flex flex-col justify-center rounded-md px-2.5 text-left text-xs shadow-sm transition-shadow hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 ${
                  operator.materializing ? looks.materializing : looks.passThrough
                } ${isSelected ? 'ring-3 ring-blue-500 ring-offset-1 ring-offset-white dark:ring-blue-400 dark:ring-offset-neutral-900' : ''}`}
              >
                <span className="flex items-center justify-between gap-2 text-[0.7rem] font-semibold tracking-wide text-neutral-600 uppercase dark:text-neutral-300">
                  <span>{kindLabels[operator.kind]}</span>
                  {isTarget && (
                    <span className="rounded bg-blue-100 px-1 text-[0.65rem] font-medium tracking-normal text-blue-800 normal-case dark:bg-blue-950 dark:text-blue-200">
                      widget
                    </span>
                  )}
                </span>
                <span className="truncate font-medium text-neutral-900 dark:text-neutral-100" title={name}>
                  {name}
                </span>
              </button>
            )
          })}
        </div>
      </div>
      <p id={hintId} className="sr-only">
        The arrow keys move along the edges and up and down a column.
      </p>
      <Legend id={legendId} />
    </div>
  )
}

/** Where an arrow key goes from a node: along an edge, or within its column. */
function neighbour(graph: Graph, node: GraphNode, key: string): OperatorId | undefined {
  const id = node.operator.id
  switch (key) {
    case 'ArrowLeft':
      return graph.edges.find((edge) => edge.to === id)?.from
    case 'ArrowRight':
      return graph.edges.find((edge) => edge.from === id)?.to
    case 'ArrowUp':
    case 'ArrowDown': {
      const row = node.row + (key === 'ArrowUp' ? -1 : 1)
      return graph.nodes.find((other) => other.layer === node.layer && other.row === row)?.operator.id
    }
  }
}

function Legend({ id }: { id: string }) {
  const swatch = 'inline-block h-3 w-5 rounded-sm'
  return (
    <ul
      id={id}
      aria-label="Legend"
      className="flex flex-wrap gap-x-4 gap-y-1 border-t border-neutral-200 px-3 py-2 text-xs text-neutral-600 dark:border-neutral-800 dark:text-neutral-400"
    >
      <li className="flex items-center gap-1.5">
        <span aria-hidden="true" className={`${swatch} ${looks.materializing}`} />
        Materializing: stores a snapshot of its output
      </li>
      <li className="flex items-center gap-1.5">
        <span aria-hidden="true" className={`${swatch} ${looks.passThrough}`} />
        Pass-through: computed from its inputs when read
      </li>
      <li className="flex items-center gap-1.5">
        <span aria-hidden="true" className={`${swatch} ring-2 ring-blue-500 dark:ring-blue-400`} />
        Selected
      </li>
    </ul>
  )
}
