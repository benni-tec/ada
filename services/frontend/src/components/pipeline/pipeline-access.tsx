import { useQuery, useQueryClient } from '@tanstack/react-query'
import { SquareArrowOutUpRight } from 'lucide-react'
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'

import { Modal } from '@/components/modal'
import { ErrorNotice, Loading } from '@/components/notices'
import { Button } from '@/components/ui/button'
import {
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

import { kindLabels, shortName, type SourceInfo } from './labels'
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
 * "Pipeline" at the left of the card's footer: one button that opens the widget's
 * pipeline as a graph. Every card has one: whoever doubts a number can follow it back to
 * its source and fetch time, in the card's own run. The pipeline is read only when the
 * dialog opens, so a page of cards asks for none.
 */
export function PipelineAccess({ widget, run }: { widget: Widget; run: CardRun }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="xs"
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
        className="text-muted-foreground"
      >
        Pipeline
        <SquareArrowOutUpRight aria-hidden="true" data-icon="inline-end" />
      </Button>
      {/* What is left of the line, so the icon actions sit at the right. */}
      <span className="flex-1" />
      {open && <PipelineDialog widget={widget} run={run} onClose={() => setOpen(false)} />}
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

/** The pipeline dialog. The pipeline is read when it opens. */
function PipelineDialog({ widget, run, onClose }: { widget: Widget; run: CardRun; onClose: () => void }) {
  const lineage = useQuery(lineageQuery(widget.operator_id))
  const sourceOf = useSourceOf(widget.project_id, run.sources)
  return (
    <Modal title={`Pipeline of “${widget.title || 'Untitled widget'}”`} description={<RunLine run={run} />} onClose={onClose}>
      {lineage.isPending ? (
        <div className="p-4">
          <Loading what="the pipeline" />
        </div>
      ) : lineage.error ? (
        <div className="p-4">
          <ErrorNotice error={lineage.error} prefix="The pipeline cannot be loaded:" />
        </div>
      ) : (
        <PipelineView widget={widget} run={run} operators={lineage.data} sourceOf={sourceOf} />
      )}
    </Modal>
  )
}

/**
 * The pipeline as a graph, the selected operator's details beside it and its first rows in
 * the card's run below. The widget's operator is selected first: it is what the card shows.
 */
function PipelineView({
  widget,
  run,
  operators,
  sourceOf,
}: {
  widget: Widget
  run: CardRun
  operators: readonly Operator[]
  sourceOf: (operator: Operator) => SourceInfo | undefined
}) {
  const queryClient = useQueryClient()
  const previewId = useId()
  const view = useRef<HTMLDivElement>(null)
  // The pipeline arrives after the dialog opened: the focus then moves to the widget's
  // operator, the node the dialog is about (until then the dialog had only its ×).
  useEffect(() => {
    view.current?.querySelector<HTMLElement>('[data-autofocus]')?.focus()
  }, [])
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
    <div ref={view} className="grid h-full min-h-0 grid-cols-1 overflow-y-auto lg:grid-cols-[minmax(0,1fr)_minmax(20rem,26rem)] lg:grid-rows-[minmax(0,1fr)_minmax(9rem,18rem)] lg:overflow-hidden">
      <section aria-label="Graph" className="flex h-80 min-h-0 flex-col lg:h-auto">
        <PipelineGraph
          operators={operators}
          target={widget.operator_id}
          selected={selected.id}
          onSelect={setSelectedId}
          sourceOf={sourceOf}
        />
      </section>
      <aside aria-label="Details" className="min-h-0 border-t p-4 lg:overflow-y-auto lg:border-t-0 lg:border-l">
        <OperatorDetails operator={selected} run={stored.data ?? null} sourceOf={sourceOf} nameOf={nameOf} />
      </aside>
      <section aria-labelledby={previewId} className="flex h-72 min-h-0 flex-col border-t lg:col-span-2 lg:h-auto">
        <h3 id={previewId} className="px-3 pt-2 text-sm font-semibold">
          Preview: {nameOf(selected.id)}
        </h3>
        <RowsPreview key={selected.id} runId={run.id} operatorId={selected.id} total={snapshot.data?.row_count} />
      </section>
    </div>
  )
}
