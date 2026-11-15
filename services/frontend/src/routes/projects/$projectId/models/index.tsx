import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'

import { RunsBadge } from '@/components/cases/labels'
import { ErrorNotice } from '@/components/notices'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  caseKeys,
  caseTypesQuery,
  createPathwayModel,
  modelCasesQuery,
  statisticalModelKeys,
  statisticalModelsQuery,
  type CaseType,
  type StatisticalModel,
} from '@/lib/api'
import { day } from '@/lib/cases'

export const Route = createFileRoute('/projects/$projectId/models/')({
  component: ModelsPage,
})

/** The project's models, each with its case type, when it runs and how many of its cases
 * have a result; and the button that creates the shipped one. */
function ModelsPage() {
  const { projectId } = Route.useParams()
  const queryClient = useQueryClient()
  const { data: models } = useQuery(statisticalModelsQuery(projectId))
  const { data: caseTypes } = useQuery(caseTypesQuery(projectId))
  const create = useMutation({
    mutationFn: () => createPathwayModel(projectId),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: statisticalModelKeys.list(projectId) }),
        queryClient.invalidateQueries({ queryKey: caseKeys.types(projectId) }),
      ]),
  })
  return (
    <div className="flex max-w-6xl flex-col gap-6 p-4 md:p-6">
      <PageHeader
        type="model"
        typeLabel="Models"
        title="Models"
        below={<p className="text-sm text-muted-foreground">Each model runs on one case type.</p>}
        actions={
          <Button onClick={() => create.mutate()} disabled={create.isPending}>
            Create the patient pathway model
          </Button>
        }
      />
      {create.isError && <ErrorNotice error={create.error} />}
      {models && models.length === 0 ? (
        <p className="text-sm text-muted-foreground">No models yet.</p>
      ) : (
        <div className="rounded-xl border bg-card">
          <Table className="min-w-[720px]">
            <TableHeader>
              <TableRow>
                <TableHead className="px-4 text-xs text-muted-foreground">Model</TableHead>
                <TableHead className="px-4 text-xs text-muted-foreground">Case type</TableHead>
                <TableHead className="px-4 text-xs text-muted-foreground">Runs</TableHead>
                <TableHead className="px-4 text-xs text-muted-foreground">Version</TableHead>
                <TableHead className="px-4 text-xs text-muted-foreground">Eligible cases</TableHead>
                <TableHead className="px-4 text-xs text-muted-foreground">With a result</TableHead>
                <TableHead className="px-4 text-xs text-muted-foreground">Updated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {models?.map((model) => (
                <ModelRow key={model.id} projectId={projectId} model={model} caseTypes={caseTypes ?? []} />
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}

function ModelRow({ projectId, model, caseTypes }: { projectId: string; model: StatisticalModel; caseTypes: readonly CaseType[] }) {
  const caseType = caseTypes.find((t) => t.id === model.case_type_id)
  const { data: cases } = useQuery({ ...modelCasesQuery(model.id), enabled: model.case_type_id != null })
  const eligible = cases?.length
  const withResult = cases?.filter((row) => row.latest !== null).length
  return (
    <TableRow>
      <TableCell className="px-4 py-3 whitespace-normal">
        <Link
          to="/projects/$projectId/models/$modelId"
          params={{ projectId, modelId: model.id }}
          className="font-medium underline-offset-4 hover:underline"
        >
          {model.name}
        </Link>
        <div className="max-w-sm text-xs text-muted-foreground">{model.description}</div>
      </TableCell>
      <TableCell className="px-4 py-3">{caseType?.name ?? <span className="text-muted-foreground">–</span>}</TableCell>
      <TableCell className="px-4 py-3">
        <RunsBadge autoRun={model.auto_run} />
      </TableCell>
      <TableCell className="px-4 py-3">v{model.latest_version}</TableCell>
      <TableCell className="px-4 py-3 tabular-nums">{eligible ?? '–'}</TableCell>
      <TableCell className="px-4 py-3 tabular-nums">
        {withResult === undefined || eligible === undefined ? (
          '–'
        ) : (
          <>
            {withResult}
            {eligible > 0 && <span className="text-xs text-muted-foreground"> · {Math.round((withResult / eligible) * 100)} %</span>}
          </>
        )}
      </TableCell>
      <TableCell className="px-4 py-3 text-xs text-muted-foreground">{day(model.updated_at ?? model.created_at)}</TableCell>
    </TableRow>
  )
}
