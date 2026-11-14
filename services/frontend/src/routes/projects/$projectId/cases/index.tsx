import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { Plus } from 'lucide-react'
import { useState } from 'react'

import { Filters } from '@/components/cases/filters'
import { ResultBadge } from '@/components/cases/labels'
import { ErrorNotice, Loading } from '@/components/notices'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  casesQuery,
  caseTypesQuery,
  modelCasesQuery,
  openCasesQuery,
  statisticalModelsQuery,
  type Case,
  type CaseResult,
  type CaseType,
  type Id,
  type StatisticalModel,
} from '@/lib/api'
import { day, displayValue } from '@/lib/cases'

export const Route = createFileRoute('/projects/$projectId/cases/')({
  component: CasesPage,
})

/** The project's case types, each with its cases and the way to add one. */
function CasesPage() {
  const { projectId } = Route.useParams()
  const { data: caseTypes, error } = useQuery(caseTypesQuery(projectId))
  const { data: models } = useQuery(statisticalModelsQuery(projectId))
  const only = caseTypes?.length === 1 ? caseTypes[0] : undefined

  return (
    <div className="flex max-w-6xl flex-col gap-6 p-4 md:p-6">
      <PageHeader
        type="case"
        typeLabel="Cases"
        title={only ? only.name : 'Cases'}
        below={
          <p className="max-w-3xl text-sm text-muted-foreground">
            {only?.description || 'Each case is saved under a key from your system. Saving one runs the models set to run automatically.'}
          </p>
        }
        actions={only && <NewCase projectId={projectId} caseTypeId={only.id} />}
      />
      {error && <ErrorNotice error={error} />}
      {!caseTypes && !error && <Loading what="the case types" />}
      {caseTypes?.length === 0 && (
        <p className="text-sm text-muted-foreground">No case types yet. Creating the patient pathway model adds one.</p>
      )}
      {caseTypes?.map((caseType) => (
        <CaseTypeCases
          key={caseType.id}
          projectId={projectId}
          caseType={caseType}
          model={headlineModel(models ?? [], caseType.id)}
          titled={!only}
        />
      ))}
    </div>
  )
}

function NewCase({ projectId, caseTypeId }: { projectId: Id; caseTypeId: Id }) {
  return (
    <Button asChild>
      <Link to="/projects/$projectId/cases/new" params={{ projectId }} search={{ type: caseTypeId }}>
        <Plus aria-hidden="true" />
        New case
      </Link>
    </Button>
  )
}

/** The model whose latest result the list shows: the pathway model, else one that runs
 * automatically, else any model on the type. */
function headlineModel(models: readonly StatisticalModel[], caseTypeId: Id) {
  const on = models.filter((m) => m.case_type_id === caseTypeId)
  return on.find((m) => m.kind === 'patient_pathway') ?? on.find((m) => m.auto_run) ?? on[0]
}

type View = 'all' | 'open'

/** One case type's cases: all of them, newest first, or the open ones by deadline. */
function CaseTypeCases({
  projectId,
  caseType,
  model,
  titled,
}: {
  projectId: Id
  caseType: CaseType
  model: StatisticalModel | undefined
  titled: boolean
}) {
  const [view, setView] = useState<View>('all')
  const { data: cases } = useQuery(casesQuery(caseType.id))
  const { data: open } = useQuery(openCasesQuery(caseType.id))
  const { data: results } = useQuery({ ...modelCasesQuery(model?.id ?? ''), enabled: model !== undefined })
  const latest = new Map<Id, CaseResult>()
  for (const row of results ?? []) if (row.latest) latest.set(row.case.id, row.latest)
  for (const row of open ?? []) if (row.latest && !latest.has(row.case.id)) latest.set(row.case.id, row.latest)

  const rows: Case[] =
    view === 'open'
      ? (open ?? []).map((row) => row.case)
      : [...(cases ?? [])].sort((a, b) => b.updated_at.localeCompare(a.updated_at))
  const field = (name: string) => caseType.fields.find((f) => f.name === name)
  const county = field('county')
  const site = field('site')

  return (
    <section className="rounded-xl border bg-card" aria-label={caseType.name}>
      <header className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        {titled ? <h2 className="font-semibold">{caseType.name}</h2> : <h2 className="font-semibold">Cases</h2>}
        <div className="flex flex-wrap items-center gap-3">
          <Filters
            label="Filter cases"
            value={view}
            onChange={setView}
            options={[
              { value: 'all', label: 'All', count: cases?.length },
              { value: 'open', label: 'Open', count: open?.length },
            ]}
          />
          {titled && <NewCase projectId={projectId} caseTypeId={caseType.id} />}
        </div>
      </header>
      {!cases ? (
        <div className="p-4">
          <Loading what="the cases" />
        </div>
      ) : rows.length === 0 ? (
        <p className="p-4 text-sm text-muted-foreground">{view === 'open' ? 'No open cases.' : 'No cases yet.'}</p>
      ) : (
        <Table className="min-w-[560px]">
          <TableHeader>
            <TableRow>
              <TableHead className="px-4 text-xs text-muted-foreground">Key</TableHead>
              {county && <TableHead className="px-4 text-xs text-muted-foreground">County</TableHead>}
              {site && <TableHead className="px-4 text-xs text-muted-foreground">Site</TableHead>}
              <TableHead className="px-4 text-xs text-muted-foreground">Latest result</TableHead>
              <TableHead className="px-4 text-xs text-muted-foreground">Updated</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((c) => {
              const result = latest.get(c.id)
              return (
                <TableRow key={c.id}>
                  <TableCell className="px-4 py-3">
                    <Link
                      to="/projects/$projectId/cases/$caseTypeId/$key"
                      params={{ projectId, caseTypeId: caseType.id, key: c.key }}
                      className="font-mono text-xs font-medium underline-offset-4 hover:underline"
                    >
                      {c.key}
                    </Link>
                  </TableCell>
                  {county && <TableCell className="px-4 py-3">{displayValue(county, c.values.county)}</TableCell>}
                  {site && <TableCell className="px-4 py-3">{displayValue(site, c.values.site)}</TableCell>}
                  <TableCell className="px-4 py-3">
                    {result ? <ResultBadge section={result.section} /> : <span className="text-xs text-muted-foreground">No result</span>}
                  </TableCell>
                  <TableCell className="px-4 py-3 text-xs text-muted-foreground">{day(c.updated_at)}</TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}
    </section>
  )
}
