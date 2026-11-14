import { useState, type ReactNode } from 'react'

import type { Column } from '@/lib/api'

import {
  addOperand,
  arithmeticOps,
  canRemove,
  canUnwrap,
  changeKind,
  compareOps,
  describe,
  kindLabels,
  move,
  parentOf,
  remove,
  replace,
  timeKinds,
  unwrap,
  wrap,
  type FormulaNode,
  type NodeKind,
} from './formula'

type ValueKind = 'number' | 'text' | 'boolean' | 'date' | 'timestamp'

const valueKinds: Record<ValueKind, string> = {
  number: 'Number',
  text: 'Text',
  boolean: 'True or false',
  date: 'Date',
  timestamp: 'Timestamp',
}

const fieldClass =
  'rounded-md border border-neutral-300 bg-white px-2 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-900'
const actionClass =
  'rounded-md border border-neutral-300 px-2 py-0.5 text-xs hover:bg-neutral-100 disabled:opacity-40 dark:border-neutral-700 dark:hover:bg-neutral-800'

/** The kinds offered, in the order a person usually needs them. */
const kinds = Object.keys(kindLabels) as NodeKind[]

/**
 * Builds a rule's condition as a tree: every node is a row with its kind and settings, and
 * its operands nested below it. Nodes can be added (to and/or), nested (wrapped in another
 * node), reordered among their siblings and removed. The node a server error names is
 * marked, so the person sees which part to fix.
 */
export function FormulaBuilder({
  value,
  onChange,
  columns,
  invalidNodeId,
  timeRole,
}: {
  value: FormulaNode
  onChange: (next: FormulaNode) => void
  columns: readonly Column[]
  invalidNodeId?: string | null
  /** Whether the measure declares a time role; time functions need one. */
  timeRole: boolean
}) {
  return (
    <div className="flex flex-col gap-3">
      <ol className="flex flex-col gap-2" aria-label="Condition tree">
        <NodeEditor
          node={value}
          tree={value}
          onChange={onChange}
          columns={columns}
          invalidNodeId={invalidNodeId ?? null}
          timeRole={timeRole}
        />
      </ol>
      <p className="text-sm">
        <span className="text-neutral-600 dark:text-neutral-400">Alerts when </span>
        <code aria-label="Condition" className="rounded bg-neutral-100 px-1.5 py-0.5 font-mono dark:bg-neutral-800">
          {describe(value)}
        </code>
      </p>
    </div>
  )
}

function NodeEditor({
  node,
  tree,
  onChange,
  columns,
  invalidNodeId,
  timeRole,
}: {
  node: FormulaNode
  tree: FormulaNode
  onChange: (next: FormulaNode) => void
  columns: readonly Column[]
  invalidNodeId: string | null
  timeRole: boolean
}) {
  const set = (change: Partial<FormulaNode>) => onChange(replace(tree, node.id, (current) => ({ ...current, ...change })))
  const found = parentOf(tree, node.id)
  const siblings = found?.parent.args?.length ?? 0
  const invalid = node.id === invalidNodeId
  const label = `${kindLabels[node.kind]} ${node.id}`
  const offered = kinds.filter((kind) => timeRole || !timeKinds.includes(kind) || kind === node.kind)

  return (
    <li
      role="group"
      aria-label={label}
      aria-invalid={invalid || undefined}
      className={`flex flex-col gap-2 rounded-md border px-3 py-2 ${
        invalid
          ? 'border-red-500 bg-red-50 dark:border-red-500 dark:bg-red-950/40'
          : 'border-neutral-200 dark:border-neutral-800'
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={`Kind of ${node.id}`}
          value={node.kind}
          onChange={(event) => onChange(changeKind(tree, node.id, event.target.value as NodeKind, columns))}
          className={fieldClass}
        >
          {offered.map((kind) => (
            <option key={kind} value={kind}>
              {kindLabels[kind]}
            </option>
          ))}
        </select>
        <Settings node={node} set={set} columns={columns} />
        <span className="font-mono text-xs text-neutral-500" aria-hidden="true">
          {node.id}
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-1">
          {found && (
            <>
              <button
                type="button"
                className={actionClass}
                aria-label={`Move ${node.id} up`}
                disabled={found.index === 0}
                onClick={() => onChange(move(tree, node.id, -1))}
              >
                ↑
              </button>
              <button
                type="button"
                className={actionClass}
                aria-label={`Move ${node.id} down`}
                disabled={found.index === siblings - 1}
                onClick={() => onChange(move(tree, node.id, 1))}
              >
                ↓
              </button>
            </>
          )}
          <select
            aria-label={`Nest ${node.id} in`}
            value=""
            onChange={(event) => {
              if (event.target.value) onChange(wrap(tree, node.id, event.target.value as NodeKind, columns))
            }}
            className={`${fieldClass} py-0.5 text-xs`}
          >
            <option value="">Nest in…</option>
            {offered
              .filter((kind) => kind !== 'column' && kind !== 'constant')
              .map((kind) => (
                <option key={kind} value={kind}>
                  {kindLabels[kind]}
                </option>
              ))}
          </select>
          {(node.kind === 'and' || node.kind === 'or') && (
            <button
              type="button"
              className={actionClass}
              onClick={() => onChange(addOperand(tree, node.id, columns))}
              aria-label={`Add a condition to ${node.id}`}
            >
              + Condition
            </button>
          )}
          {canUnwrap(node) && (
            <button
              type="button"
              className={actionClass}
              onClick={() => onChange(unwrap(tree, node.id))}
              aria-label={`Unwrap ${node.id}`}
              title="Replace this node by its first operand"
            >
              Unwrap
            </button>
          )}
          {canRemove(tree, node.id) && (
            <button
              type="button"
              className={`${actionClass} text-red-700 dark:text-red-400`}
              onClick={() => onChange(remove(tree, node.id))}
              aria-label={`Remove ${node.id}`}
            >
              Remove
            </button>
          )}
        </div>
      </div>
      {node.args && node.args.length > 0 && (
        <ol className="ml-2 flex flex-col gap-2 border-l-2 border-neutral-200 pl-3 dark:border-neutral-800">
          {node.args.map((arg) => (
            <NodeEditor
              key={arg.id}
              node={arg}
              tree={tree}
              onChange={onChange}
              columns={columns}
              invalidNodeId={invalidNodeId}
              timeRole={timeRole}
            />
          ))}
        </ol>
      )}
    </li>
  )
}

function Settings({
  node,
  set,
  columns,
}: {
  node: FormulaNode
  set: (change: Partial<FormulaNode>) => void
  columns: readonly Column[]
}): ReactNode {
  switch (node.kind) {
    case 'column':
      return (
        <select
          aria-label={`Column of ${node.id}`}
          value={node.column ?? ''}
          onChange={(event) => set({ column: event.target.value })}
          className={fieldClass}
        >
          {!columns.some((column) => column.name === node.column) && <option value={node.column ?? ''}>{node.column}</option>}
          {columns.map((column) => (
            <option key={column.name} value={column.name}>
              {column.name} ({column.type})
            </option>
          ))}
        </select>
      )
    case 'constant':
      return <ConstantSettings node={node} set={set} />
    case 'compare':
    case 'arithmetic': {
      const ops = node.kind === 'compare' ? compareOps : arithmeticOps
      return (
        <select
          aria-label={`Operator of ${node.id}`}
          value={node.op ?? ops[0]}
          onChange={(event) => set({ op: event.target.value })}
          className={`${fieldClass} font-mono`}
        >
          {ops.map((op) => (
            <option key={op} value={op}>
              {op}
            </option>
          ))}
        </select>
      )
    }
    case 'previous':
    case 'change':
    case 'rolling_mean':
      return (
        <label className="flex items-center gap-1 text-sm">
          <span className="text-neutral-600 dark:text-neutral-400">over</span>
          <input
            type="number"
            min={1}
            max={1000}
            aria-label={`Periods of ${node.id}`}
            value={node.periods ?? 1}
            onChange={(event) => set({ periods: Math.max(1, Math.trunc(Number(event.target.value) || 1)) })}
            className={`${fieldClass} w-20`}
          />
          <span className="text-neutral-600 dark:text-neutral-400">{(node.periods ?? 1) === 1 ? 'period' : 'periods'}</span>
        </label>
      )
    default:
      return null
  }
}

function valueKindOf(node: FormulaNode): ValueKind {
  if (node.type) return node.type
  if (typeof node.value === 'boolean') return 'boolean'
  if (typeof node.value === 'string') return 'text'
  return 'number'
}

const defaults: Record<ValueKind, Pick<FormulaNode, 'value' | 'type'>> = {
  number: { value: 0, type: undefined },
  text: { value: '', type: undefined },
  boolean: { value: true, type: undefined },
  date: { value: '2024-01-01', type: 'date' },
  timestamp: { value: '2024-01-01T00:00:00', type: 'timestamp' },
}

function ConstantSettings({ node, set }: { node: FormulaNode; set: (change: Partial<FormulaNode>) => void }) {
  const kind = valueKindOf(node)
  return (
    <>
      <select
        aria-label={`Type of ${node.id}`}
        value={kind}
        onChange={(event) => set(defaults[event.target.value as ValueKind])}
        className={fieldClass}
      >
        {(Object.keys(valueKinds) as ValueKind[]).map((option) => (
          <option key={option} value={option}>
            {valueKinds[option]}
          </option>
        ))}
      </select>
      {kind === 'boolean' ? (
        <select
          aria-label={`Value of ${node.id}`}
          value={String(node.value)}
          onChange={(event) => set({ value: event.target.value === 'true' })}
          className={fieldClass}
        >
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      ) : kind === 'number' ? (
        <NumberInput key={node.id} id={node.id} value={Number(node.value ?? 0)} onChange={(value) => set({ value })} />
      ) : (
        <input
          aria-label={`Value of ${node.id}`}
          type={kind === 'date' ? 'date' : 'text'}
          value={String(node.value ?? '')}
          onChange={(event) => set({ value: event.target.value })}
          className={`${fieldClass} w-40`}
        />
      )}
    </>
  )
}

/** Keeps what is typed while it is not a number yet ("", "-"); the tree gets numbers only. */
function NumberInput({ id, value, onChange }: { id: string; value: number; onChange: (value: number) => void }) {
  // The draft belongs to the value it was typed for; a value changed from elsewhere wins.
  const [typed, setTyped] = useState({ draft: String(value), for: value })
  const draft = typed.for === value ? typed.draft : String(value)
  return (
    <input
      aria-label={`Value of ${id}`}
      type="number"
      step="any"
      value={draft}
      onChange={(event) => {
        const raw = event.target.value
        const parsed = raw.trim() !== '' && Number.isFinite(Number(raw)) ? Number(raw) : null
        setTyped({ draft: raw, for: parsed ?? value })
        if (parsed !== null) onChange(parsed)
      }}
      className={`${fieldClass} w-28`}
    />
  )
}
