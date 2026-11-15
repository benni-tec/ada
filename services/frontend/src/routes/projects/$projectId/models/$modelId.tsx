import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useState } from 'react'

import { Filters } from '@/components/cases/filters'
import { ResultBadge, RunsBadge } from '@/components/cases/labels'
import { ResultSheet, type SheetTarget } from '@/components/cases/result-sheet'
import { EvaluationTab } from '@/components/models/evaluation'
import { ModelCard } from '@/components/models/model-card'
import { PopulationTab } from '@/components/models/population'
import { ErrorNotice, Loading } from '@/components/notices'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  caseTypeQuery,
  evaluateCase,
  invalidateCase,
  latestVersionQuery,
  modelCasesQuery,
  statisticalModelQuery,
  type CaseType,
  type CaseWithResult,
  type Id,
  type Section,
  type StatisticalModel,
} from '@/lib/api'
import { displayValue, triggerLabel, when } from '@/lib/cases'

const views = ['card', 'cases', 'evaluation', 'population'] as const
type View = (typeof views)[number]

export const Route = createFileRoute('/projects/$projectId/models/$modelId')({
  validateSearch: (search: Record<string, unknown>): { view?: View } =>
    views.includes(search.view as View) && search.view !== 'card' ? { view: search.view as View } : {},
  component: ModelPage,
})

/** One model: its card first, then its cases (every case of its case type, with the
 * model's latest result), the evaluation of a synthetic profile and the population view. */
function ModelPage() {
  const { projectId, modelId } = Route.useParams()
  const { view = 'card' } = Route.useSearch()
  const navigate = Route.useNavigate()
  const { data: model, error: modelError } = useQuery(statisticalModelQuery(modelId))
  const { data: version, error: versionError } = useQuery(latestVersionQuery(modelId))
  const { data: caseType } = useQuery({ ...caseTypeQuery(model?.case_type_id ?? ''), enabled: model?.case_type_id != null })
  const error = modelError ?? versionError
  if (error)
    return (
      <div className="p-4 md:p-6">
        <ErrorNotice error={error} prefix="Could not load the model:" />
      </div>
    )
  if (!model || !version)
    return (
      <div className="p-4 md:p-6">
        <Loading what="the model" />
      </div>
    )
  return (
    <div className="flex max-w-6xl flex-col gap-6 p-4 md:p-6">
      <PageHeader
        type="model"
        typeLabel={
          <>
            <Link to="/projects/$projectId/models" params={{ projectId }} className="hover:text-foreground">
              Models
            </Link>
            <span aria-hidden="true">/</span>
            <span>{model.name}</span>
          </>
        }
        title={model.name}
        below={
          <p className="flex flex-wrap items-center gap-x-3.5 gap-y-1 text-sm text-muted-foreground">
            <span>v{version.version}</span>
            <span>Case type: {caseType?.name ?? (model.case_type_id ? '…' : 'none')}</span>
            <RunsBadge autoRun={model.auto_run} long />
          </p>
        }
      />
      <Tabs value={view} onValueChange={(next) => void navigate({ search: next === 'card' ? {} : { view: next as View }, replace: true })}>
        <TabsList variant="line" className="w-full justify-start">
          <TabsTrigger value="card">Model card</TabsTrigger>
          <TabsTrigger value="cases">Cases</TabsTrigger>
          <TabsTrigger value="evaluation">Evaluation</TabsTrigger>
          <TabsTrigger value="population">Population</TabsTrigger>
        </TabsList>
        <TabsContent value="cases" className="pt-4">
          <ModelCases projectId={projectId} model={model} caseType={caseType} />
        </TabsContent>
        <TabsContent value="card" className="pt-4">
          <ModelCard version={version} />
        </TabsContent>
        <TabsContent value="evaluation" className="pt-4">
          <EvaluationTab modelId={modelId} version={version} />
        </TabsContent>
        <TabsContent value="population" className="pt-4">
          <PopulationTab modelId={modelId} version={version} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

// What a pathway result's columns say: open until treatment has started; overdue when a
// deadline is.
const isOpen = (s: Section) => s.columns.trigger !== 'none' && !['met', 'late'].includes(String(s.columns.treatment_start_status))
const isOverdue = (s: Section) => Object.entries(s.columns).some(([k, v]) => k.endsWith('_status') && v === 'overdue')

type Filter = 'all' | 'overdue' | 'open' | 'not_run'

const filters: Record<Filter, (row: CaseWithResult) => boolean> = {
  all: () => true,
  overdue: (row) => row.latest !== null && isOpen(row.latest.section) && isOverdue(row.latest.section),
  open: (row) => row.latest !== null && isOpen(row.latest.section),
  not_run: (row) => row.latest === null,
}

function ModelCases({ projectId, model, caseType }: { projectId: Id; model: StatisticalModel; caseType: CaseType | undefined }) {
  const queryClient = useQueryClient()
  const { data: rows, error } = useQuery({ ...modelCasesQuery(model.id), enabled: model.case_type_id != null })
  const [filter, setFilter] = useState<Filter>('all')
  const [sheet, setSheet] = useState<{ key: string; target: SheetTarget } | null>(null)
  const evaluate = useMutation({
    mutationFn: (key: string) => evaluateCase(model.case_type_id ?? '', key, model.id),
    onSuccess: async (result, key) => {
      setSheet({ key, target: { modelId: model.id, modelName: model.name, result } })
      await invalidateCase(queryClient, model.case_type_id ?? '', key)
    },
  })

  if (model.case_type_id == null) return <p className="text-sm text-muted-foreground">This model is not on a case type.</p>
  if (error) return <ErrorNotice error={error} />
  if (!rows) return <Loading what="the cases" />

  const withResult = rows.filter((row) => row.latest !== null)
  const started = withResult.filter((row) => ['met', 'late'].includes(String(row.latest?.section.columns.treatment_start_status)))
  const onTarget = started.filter((row) => row.latest?.section.columns.treatment_start_status === 'met')
  const field = (name: string) => caseType?.fields.find((f) => f.name === name)
  const county = field('county')
  const site = field('site')
  const shown = rows.filter(filters[filter])
  const count = (f: Filter) => rows.filter(filters[f]).length

  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-3">
        <Stat value={rows.length} label="eligible cases" />
        <Stat value={withResult.length} label="with a result" />
        <Stat value={count('overdue')} label="open, a deadline overdue" warn={count('overdue') > 0} />
        <Stat value={started.length > 0 ? `${Math.round((onTarget.length / started.length) * 100)} %` : '–'} label="treatment started on target" />
      </div>

      <section className="rounded-xl border bg-card" aria-labelledby="model-cases-title">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
          <h2 id="model-cases-title" className="font-semibold">
            Cases
          </h2>
          <Filters
            label="Filter cases"
            value={filter}
            onChange={setFilter}
            options={[
              { value: 'all', label: 'All', count: rows.length },
              { value: 'overdue', label: 'Overdue', count: count('overdue') },
              { value: 'open', label: 'Open', count: count('open') },
              { value: 'not_run', label: 'Not run', count: count('not_run') },
            ]}
          />
        </header>
        {shown.length === 0 ? (
          <p className="p-4 text-sm text-muted-foreground">{rows.length === 0 ? 'No cases of this case type yet.' : 'No cases in this view.'}</p>
        ) : (
          <Table className="min-w-[680px]">
            <TableHeader>
              <TableRow>
                <TableHead className="px-4 text-xs text-muted-foreground">Key</TableHead>
                {county && <TableHead className="px-4 text-xs text-muted-foreground">County</TableHead>}
                {site && <TableHead className="px-4 text-xs text-muted-foreground">Site</TableHead>}
                <TableHead className="px-4 text-xs text-muted-foreground">Latest result</TableHead>
                <TableHead className="px-4 text-xs text-muted-foreground">Ran</TableHead>
                <TableHead className="px-4">
                  <span className="sr-only">Actions</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shown.map(({ case: c, latest }) => (
                <TableRow key={c.id} data-case={c.key}>
                  <TableCell className="px-4 py-3">
                    <Link
                      to="/projects/$projectId/cases/$caseTypeId/$key"
                      params={{ projectId, caseTypeId: c.case_type_id, key: c.key }}
                      className="font-mono text-xs font-medium underline-offset-4 hover:underline"
                    >
                      {c.key}
                    </Link>
                  </TableCell>
                  {county && <TableCell className="px-4 py-3">{displayValue(county, c.values.county)}</TableCell>}
                  {site && <TableCell className="px-4 py-3">{displayValue(site, c.values.site)}</TableCell>}
                  <TableCell className="px-4 py-3">{latest ? <ResultBadge section={latest.section} /> : <span className="text-xs text-muted-foreground">–</span>}</TableCell>
                  <TableCell className="px-4 py-3 text-xs text-muted-foreground">
                    {latest ? `${triggerLabel(latest)} · ${when(latest.created_at)}` : 'Not run'}
                  </TableCell>
                  <TableCell className="px-4 py-3 text-right">
                    {latest ? (
                      <Button variant="outline" onClick={() => setSheet({ key: c.key, target: { modelId: model.id, modelName: model.name, result: latest } })}>
                        View
                      </Button>
                    ) : (
                      <Button onClick={() => evaluate.mutate(c.key)} disabled={evaluate.isPending && evaluate.variables === c.key}>
                        {evaluate.isPending && evaluate.variables === c.key ? 'Evaluating…' : 'Evaluate'}
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
        Eligible cases are all cases of the model's case type. Cases saved before the model existed show "Not run" until someone
        evaluates them.
      </p>

      <ResultSheet
        caseTypeId={model.case_type_id}
        caseKey={sheet?.key ?? ''}
        caseTypeName={caseType?.name}
        target={sheet?.target ?? null}
        onClose={() => setSheet(null)}
      />
    </div>
  )
}

function Stat({ value, label, warn }: { value: number | string; label: string; warn?: boolean }) {
  return (
    <div className="rounded-xl border px-4 py-3">
      <div className={`text-2xl font-semibold tabular-nums ${warn ? 'text-orange-700 dark:text-orange-400' : ''}`}>{value}</div>
      <div className="text-xs text-muted-foreground">{label}</div>
    </div>
  )
}
