import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { ErrorNotice } from '@/components/notices'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { caseQuery, evaluateCase, invalidateCase, type CaseResult, type Evaluation, type Id, type Section } from '@/lib/api'
import { when } from '@/lib/cases'

import { PathwayResult } from './pathway-result'

/** Which model's results the sheet shows, and the one to open at. */
export type SheetTarget = { modelId: Id; modelName: string; result?: CaseResult }

/**
 * One model's result on one case, in a sheet over the page: what it said, the earlier
 * results in a picker, and "Evaluate again", which stores a new result.
 */
export function ResultSheet({
  caseTypeId,
  caseKey,
  caseTypeName,
  target,
  onClose,
}: {
  caseTypeId: Id
  caseKey: string
  caseTypeName?: string
  target: SheetTarget | null
  onClose: () => void
}) {
  return (
    <Sheet open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-2xl">
        {target && (
          <SheetBody
            key={`${target.modelId}:${target.result?.id ?? ''}`}
            caseTypeId={caseTypeId}
            caseKey={caseKey}
            caseTypeName={caseTypeName}
            target={target}
          />
        )}
      </SheetContent>
    </Sheet>
  )
}

function SheetBody({ caseTypeId, caseKey, caseTypeName, target }: { caseTypeId: Id; caseKey: string; caseTypeName?: string; target: SheetTarget }) {
  const queryClient = useQueryClient()
  const { data: state } = useQuery(caseQuery(caseTypeId, caseKey))
  // Results made here, shown before the case is fetched again.
  const [made, setMade] = useState<CaseResult[]>(target.result ? [target.result] : [])
  const [selectedId, setSelectedId] = useState<Id | undefined>(target.result?.id)
  const results = merge([...(state?.results ?? []), ...made].filter((r) => r.model_id === target.modelId))
  const shown = results.find((r) => r.id === selectedId) ?? results[0]

  const again = useMutation({
    mutationFn: () => evaluateCase(caseTypeId, caseKey, target.modelId),
    onSuccess: async (result) => {
      setMade((current) => [result, ...current])
      setSelectedId(result.id)
      await invalidateCase(queryClient, caseTypeId, caseKey)
    },
  })

  return (
    <>
      <SheetHeader className="border-b px-5 py-4 pr-12">
        <p className="text-xs text-muted-foreground">
          <span className="font-mono">{caseKey}</span>
          {caseTypeName && ` · ${caseTypeName}`}
        </p>
        <SheetTitle className="text-lg font-semibold">{target.modelName}</SheetTitle>
        <SheetDescription className="flex flex-wrap gap-x-3.5 gap-y-0.5 text-xs">
          {shown ? (
            <>
              <span>v{shown.version}</span>
              <span>{shown.trigger === 'auto' ? 'Ran automatically' : 'Evaluated on request'}</span>
              <span>{when(shown.created_at)}</span>
              <span>read revision {shown.case_revision}</span>
            </>
          ) : (
            <span>Not evaluated for this case</span>
          )}
        </SheetDescription>
      </SheetHeader>

      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-5">
        {shown ? <SectionView section={shown.section} /> : !state ? <p className="text-sm text-muted-foreground">Loading…</p> : null}
        {again.isError && <ErrorNotice error={again.error} prefix="Could not evaluate:" />}
      </div>

      <SheetFooter className="flex-row flex-wrap items-center justify-between gap-3 border-t px-5 py-3">
        {results.length > 0 ? (
          <select
            aria-label="Earlier results"
            className="h-8 max-w-full rounded-lg border border-input bg-transparent px-2 text-sm dark:bg-input/30"
            value={shown?.id}
            onChange={(event) => setSelectedId(event.target.value)}
          >
            {results.map((r, i) => (
              <option key={r.id} value={r.id}>
                {when(r.created_at)} · rev. {r.case_revision}
                {i === 0 ? (results.length === 1 ? ' (only result)' : ' (latest)') : ''}
              </option>
            ))}
          </select>
        ) : (
          <span />
        )}
        <Button onClick={() => again.mutate()} disabled={again.isPending}>
          {again.isPending ? 'Evaluating…' : results.length > 0 ? 'Evaluate again' : 'Evaluate'}
        </Button>
      </SheetFooter>
    </>
  )
}

/** Newest first, each result once. */
function merge(results: CaseResult[]) {
  const byId = new Map(results.map((r) => [r.id, r]))
  return [...byId.values()].sort((a, b) => b.created_at.localeCompare(a.created_at))
}

/** What a model said: the pathway model's condensed result, or any other model's summary
 * and columns. */
export function SectionView({ section }: { section: Section }) {
  if (section.kind === 'patient_pathway' && isEvaluation(section.body)) {
    return <PathwayResult evaluation={section.body} summary={section.summary} />
  }
  const columns = Object.entries(section.columns)
  return (
    <div className="flex flex-col gap-4">
      <p className="rounded-lg bg-foreground px-3.5 py-3 text-sm text-background">{section.summary}</p>
      {columns.length > 0 && (
        <dl className="grid grid-cols-[minmax(0,1fr)_auto] text-sm">
          {columns.map(([name, value]) => (
            <div key={name} className="contents">
              <dt className="border-b py-1.5 text-muted-foreground">{name.replaceAll('_', ' ')}</dt>
              <dd className="border-b py-1.5 text-right font-medium">{value === null ? '–' : String(value)}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}

function isEvaluation(body: Section['body']): body is Section['body'] & Evaluation {
  return Array.isArray(body.deadlines) && Array.isArray(body.pathway) && typeof body.survival === 'object' && body.survival !== null
}
