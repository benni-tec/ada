import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'

import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { createPathwayModel, errorMessage, statisticalModelKeys, statisticalModelsQuery } from '@/lib/api'

export const Route = createFileRoute('/projects/$projectId/models/')({
  component: ModelsPage,
})

/** The project's statistical models, and the button that creates the shipped one. */
function ModelsPage() {
  const { projectId } = Route.useParams()
  const queryClient = useQueryClient()
  const { data: models } = useQuery(statisticalModelsQuery(projectId))
  const create = useMutation({
    mutationFn: () => createPathwayModel(projectId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: statisticalModelKeys.list(projectId) }),
  })
  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <PageHeader
        type="model"
        typeLabel="Models"
        title="Statistical models"
        below={
          <p className="max-w-3xl text-sm text-muted-foreground">
            Versioned models built from published figures, each with its provenance, evaluated on one synthetic profile at
            a time. Nothing an evaluation computes is stored.
          </p>
        }
        actions={
          <Button onClick={() => create.mutate()} disabled={create.isPending}>
            Create the patient pathway model
          </Button>
        }
      />
      {create.isError && <p className="text-sm text-destructive">{errorMessage(create.error)}</p>}
      {models && models.length === 0 && <p className="text-sm text-muted-foreground">No models yet.</p>}
      <ul className="flex flex-col gap-3">
        {models?.map((model) => (
          <li key={model.id} className="rounded-lg border bg-card p-4">
            <Link
              to="/projects/$projectId/models/$modelId"
              params={{ projectId, modelId: model.id }}
              className="font-medium underline-offset-4 hover:underline"
            >
              {model.name}
            </Link>
            <p className="mt-1 text-sm text-muted-foreground">{model.description}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              v{model.latest_version} · {model.kind}
            </p>
          </li>
        ))}
      </ul>
    </div>
  )
}
