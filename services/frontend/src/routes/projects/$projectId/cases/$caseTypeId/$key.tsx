import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useState } from 'react'

import { CaseData } from '@/components/cases/case-data'
import { ResultBadge, RunsBadge } from '@/components/cases/labels'
import { ResultSheet, type SheetTarget } from '@/components/cases/result-sheet'
import { ErrorNotice, Loading } from '@/components/notices'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  caseModelsQuery,
  caseQuery,
  caseTypeQuery,
  evaluateCase,
  invalidateCase,
  ownFields,
  putCase,
  ranText,
  type CaseResult,
  type CaseValues,
  type Evaluation,
  type ModelOnCase,
} from '@/lib/api'
import { when } from '@/lib/cases'
import { toast } from '@/lib/toast'

export const Route = createFileRoute('/projects/$projectId/cases/$caseTypeId/$key')({
  component: CasePage,
})

/**
 * One case: its data beside its steps, edited in place, and beneath it the models on its
 * case type with their latest result. A result opens in a side sheet over the page.
 */
function CasePage() {
  const { projectId, caseTypeId, key } = Route.useParams()
  const queryClient = useQueryClient()
  const { data: caseType } = useQuery(caseTypeQuery(caseTypeId))
  const { data: state, error } = useQuery(caseQuery(caseTypeId, key))
  const { data: models } = useQuery(caseModelsQuery(caseTypeId, key))
  const [target, setTarget] = useState<SheetTarget | null>(null)

  const save = useMutation({
    mutationFn: (values: CaseValues) => putCase(caseTypeId, key, values),
    onSuccess: async (saved) => {
      queryClient.setQueryData(caseQuery(caseTypeId, key).queryKey, saved)
      const names = saved.ran.map((id) => models?.find((m) => m.model_id === id)?.name ?? 'A model')
      toast(`Saved as revision ${saved.case.revision}. ${ranText(names)}`)
      await invalidateCase(queryClient, caseTypeId, key)
    },
  })
  const evaluate = useMutation({
    mutationFn: (model: ModelOnCase) => evaluateCase(caseTypeId, key, model.model_id),
    onSuccess: async (result, model) => {
      setTarget({ modelId: model.model_id, modelName: model.name, result })
      await invalidateCase(queryClient, caseTypeId, key)
    },
  })

  if (error) return <div className="p-4 md:p-6"><ErrorNotice error={error} /></div>
  if (!caseType || !state) return <div className="p-4 md:p-6"><Loading what="the case" /></div>

  const headline = latestHeadline(models ?? [])
  const pathway = models?.find((m) => m.kind === 'patient_pathway')?.latest?.section.body as Evaluation | undefined
  const saved = new Date(state.case.updated_at).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })

  return (
    <div className="flex max-w-6xl flex-col gap-5 p-4 md:p-6">
      <PageHeader
        type="case"
        typeLabel={
          <>
            <Link to="/projects/$projectId/cases" params={{ projectId }} className="hover:text-foreground">
              Cases
            </Link>
            <span aria-hidden="true">/</span>
            <span>{caseType.name}</span>
          </>
        }
        title={<h1 className="font-mono text-2xl font-semibold break-all">{state.case.key}</h1>}
        below={
          <p className="flex flex-wrap gap-x-3.5 gap-y-0.5 text-sm text-muted-foreground">
            <span>Revision {state.case.revision} · saved {saved}</span>
            <span>Synthetic</span>
          </p>
        }
        actions={headline && <ResultBadge section={headline.section} className="h-6 px-2.5 text-sm" />}
      />

      <CaseData
        key={state.case.revision}
        caseType={caseType}
        state={state}
        own={ownFields(caseType, models ?? [])}
        clockStart={pathway?.trigger?.clock_start ?? null}
        onSave={(values) => save.mutateAsync(values)}
        saving={save.isPending}
        error={save.error}
      />

      <section className="rounded-xl border bg-card" aria-labelledby="case-models-title">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
          <h2 id="case-models-title" className="font-semibold">
            Models
          </h2>
          {models && (
            <span className="text-xs text-muted-foreground">
              {models.length} {models.length === 1 ? 'model' : 'models'} on {caseType.name}
            </span>
          )}
        </header>
        {models && models.length === 0 ? (
          <p className="p-4 text-sm text-muted-foreground">No model runs on this case type yet.</p>
        ) : (
          <Table className="min-w-[640px]">
            <TableHeader>
              <TableRow>
                <TableHead className="px-4 text-xs text-muted-foreground">Model</TableHead>
                <TableHead className="px-4 text-xs text-muted-foreground">Runs</TableHead>
                <TableHead className="px-4 text-xs text-muted-foreground">Latest result</TableHead>
                <TableHead className="px-4 text-xs text-muted-foreground">When</TableHead>
                <TableHead className="px-4">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {models?.map((model) => (
                <TableRow key={model.model_id} data-model={model.model_id}>
                  <TableCell className="px-4 py-3">
                    <Link
                      to="/projects/$projectId/models/$modelId"
                      params={{ projectId, modelId: model.model_id }}
                      className="font-medium underline-offset-4 hover:underline"
                    >
                      {model.name}
                    </Link>
                    <div className="text-xs text-muted-foreground">v{model.version}</div>
                  </TableCell>
                  <TableCell className="px-4 py-3">
                    <RunsBadge autoRun={model.auto_run} />
                  </TableCell>
                  <TableCell className="px-4 py-3 whitespace-normal">
                    {model.latest ? <ResultBadge section={model.latest.section} /> : <span className="text-xs text-muted-foreground">Not evaluated for this case</span>}
                  </TableCell>
                  <TableCell className="px-4 py-3 text-xs text-muted-foreground">
                    {model.latest ? `${when(model.latest.created_at)} · rev. ${model.latest.case_revision}` : '–'}
                  </TableCell>
                  <TableCell className="px-4 py-3 text-right">
                    {model.latest ? (
                      <Button variant="outline" onClick={() => setTarget({ modelId: model.model_id, modelName: model.name, result: model.latest ?? undefined })}>
                        View result
                      </Button>
                    ) : (
                      <Button onClick={() => evaluate.mutate(model)} disabled={evaluate.isPending && evaluate.variables?.model_id === model.model_id}>
                        {evaluate.isPending && evaluate.variables?.model_id === model.model_id ? 'Evaluating…' : 'Evaluate'}
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        {evaluate.isError && (
          <div className="px-4 pb-3">
            <ErrorNotice error={evaluate.error} prefix="Could not evaluate:" />
          </div>
        )}
      </section>
      <p className="text-xs text-muted-foreground">
        Results are kept on the case as history. A model added later is not run on old cases until someone evaluates it here.
      </p>

      <ResultSheet caseTypeId={caseTypeId} caseKey={key} caseTypeName={caseType.name} target={target} onClose={() => setTarget(null)} />
    </div>
  )
}

/** The result the header shows: the pathway model's latest, else the newest of any model. */
function latestHeadline(models: readonly ModelOnCase[]): CaseResult | undefined {
  const pathway = models.find((m) => m.kind === 'patient_pathway' && m.latest)?.latest
  if (pathway) return pathway
  return models
    .map((m) => m.latest)
    .filter((r): r is CaseResult => r != null)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
}
