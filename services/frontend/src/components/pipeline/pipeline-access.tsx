import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useId, useMemo, useState } from 'react'

import { Modal } from '@/components/modal'
import {
  errorMessage,
  keys,
  lineageQuery,
  operatorRowsQuery,
  runQuery,
  snapshotQuery,
  sourcesQuery,
  type Operator,
  type OperatorId,
  type Widget,
} from '@/lib/api'
import type { CardRun } from '@/lib/view-run'

import { kindLabels, shortName, summary, type SourceInfo } from './labels'
import { OperatorDetails } from './operator-details'
import { PipelineGraph } from './pipeline-graph'
import { PREVIEW_ROWS, RowsPreview } from './rows-preview'

/**
 * Where each source operator's data comes from: as the report version recorded it when
 * there is one (the address it was fetched from, even if the source changed since), else
 * the project's source as it is now.
 */
function useSourceOf(projectId: string, recorded: CardRun['sources']) {
  const { data: sources } = useQuery(sourcesQuery(projectId))
  return useCallback(
    (operator: Operator): SourceInfo | undefined => {
      if (operator.kind !== 'source') return undefined
      const frozen = recorded?.find((source) => source.operator_id === operator.id)
      if (frozen) return { name: frozen.name, address: frozen.address }
      const id = (operator.params as Record<string, unknown>).data_source_id
      const current = sources?.find((source) => source.id === id)
      return current && { name: current.name, address: current.address }
    },
    [recorded, sources],
  )
}

/**
 * The widget's pipeline in one line at the left of the card's footer, e.g. "Pipeline:
 * Sotkanet screening → 2 steps → map", which opens it as a graph. Every card has one:
 * whoever doubts a number can follow it back to its source and fetch time, in the card's
 * own run.
 */
export function PipelineAccess({ widget, run }: { widget: Widget; run: CardRun }) {
  const lineage = useQuery(lineageQuery(widget.operator_id))
  const sourceOf = useSourceOf(widget.project_id, run.sources)
  const [open, setOpen] = useState(false)
  const line = lineage.isPending
    ? 'loading…'
    : lineage.error
      ? `cannot be loaded: ${errorMessage(lineage.error)}`
      : summary(lineage.data, widget.type, sourceOf)

  return (
    <>
      <button
        type="button"
        aria-haspopup="dialog"
        disabled={!lineage.isSuccess}
        onClick={() => setOpen(true)}
        title={`Open the pipeline: ${line}`}
        className="group flex min-w-0 flex-1 items-center gap-1.5 rounded-md px-1 py-1 text-left text-xs text-neutral-600 hover:bg-neutral-100 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-blue-600 disabled:cursor-default disabled:hover:bg-transparent dark:text-neutral-400 dark:hover:bg-neutral-800"
      >
        <span className="shrink-0 font-medium text-neutral-800 dark:text-neutral-200">Pipeline:</span>{' '}
        <span className="truncate group-enabled:group-hover:underline">{line}</span>
      </button>
      {open && lineage.isSuccess && (
        <PipelineDialog
          widget={widget}
          run={run}
          operators={lineage.data}
          sourceOf={sourceOf}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  )
}

/** Which run the preview shows, and what that means for its numbers. */
function RunLine({ run }: { run: CardRun }) {
  if (run.id === null) return <>{run.what}: starting the run…</>
  const id = <code className="font-mono break-all">{run.id}</code>
  return run.frozen ? (
    <>
      Frozen: {run.what}, run {id}. These numbers never change.
    </>
  ) : (
    <>
      {run.what}, follows new data (run {id}).
    </>
  )
}

/**
 * The pipeline as a graph, the selected operator's details beside it and its first rows in
 * the card's run below. The widget's operator is selected first: it is what the card shows.
 */
function PipelineDialog({
  widget,
  run,
  operators,
  sourceOf,
  onClose,
}: {
  widget: Widget
  run: CardRun
  operators: readonly Operator[]
  sourceOf: (operator: Operator) => SourceInfo | undefined
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const previewId = useId()
  const [selectedId, setSelectedId] = useState<OperatorId>(widget.operator_id)
  const byId = useMemo(() => new Map(operators.map((operator) => [operator.id, operator])), [operators])
  const selected = byId.get(selectedId) ?? operators[operators.length - 1]
  const stored = useQuery({ ...runQuery(run.id ?? ''), enabled: run.id !== null })
  const snapshotId = stored.data?.snapshots[selected.id]
  const snapshot = useQuery({ ...snapshotQuery(snapshotId ?? ''), enabled: Boolean(snapshotId) })
  const nameOf = (id: string) => {
    const operator = byId.get(id)
    return operator ? `${kindLabels[operator.kind]}: ${shortName(operator, sourceOf(operator))}` : id
  }

  // Reading a materializing operator's rows may fix its snapshot in the run just now; read
  // the run again then, so the details show it. (The preview reads; this only watches.)
  const read = useQuery({ ...operatorRowsQuery(run.id ?? '', selected.id, PREVIEW_ROWS), enabled: false }).isSuccess
  const unfixed = run.id !== null && selected.materializing && !snapshotId
  useEffect(() => {
    if (read && unfixed && run.id) void queryClient.invalidateQueries({ queryKey: keys.run(run.id) })
  }, [read, unfixed, run.id, queryClient])

  return (
    <Modal title={`Pipeline of “${widget.title || 'Untitled widget'}”`} description={<RunLine run={run} />} onClose={onClose}>
      <div className="grid h-full min-h-0 grid-cols-1 overflow-y-auto lg:grid-cols-[minmax(0,1fr)_minmax(20rem,26rem)] lg:grid-rows-[minmax(0,1fr)_minmax(9rem,18rem)] lg:overflow-hidden">
        <section aria-label="Graph" className="flex h-80 min-h-0 flex-col lg:h-auto">
          <PipelineGraph
            operators={operators}
            target={widget.operator_id}
            selected={selected.id}
            onSelect={setSelectedId}
            sourceOf={sourceOf}
          />
        </section>
        <aside
          aria-label="Details"
          className="min-h-0 border-t border-neutral-200 p-4 lg:overflow-y-auto lg:border-t-0 lg:border-l dark:border-neutral-800"
        >
          <OperatorDetails
            operator={selected}
            run={stored.data ?? null}
            sourceOf={sourceOf}
            nameOf={nameOf}
          />
        </aside>
        <section
          aria-labelledby={previewId}
          className="flex h-72 min-h-0 flex-col border-t border-neutral-200 lg:col-span-2 lg:h-auto dark:border-neutral-800"
        >
          <h3 id={previewId} className="px-3 pt-2 text-sm font-semibold">
            Preview: {nameOf(selected.id)}
          </h3>
          <RowsPreview
            key={selected.id}
            runId={run.id}
            operatorId={selected.id}
            total={snapshot.data?.row_count}
          />
        </section>
      </div>
    </Modal>
  )
}

