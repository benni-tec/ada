import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { ModelCard } from '@/components/models/model-card'
import { EvaluationTab } from '@/components/models/evaluation'
import { PopulationTab } from '@/components/models/population'
import { PageHeader } from '@/components/page-header'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { latestVersionQuery, statisticalModelQuery } from '@/lib/api'

export const Route = createFileRoute('/projects/$projectId/models/$modelId')({
  component: ModelPage,
})

/** One model: its card (structure, criteria, targets, parameters), the evaluation of a
 * synthetic profile, and the population view, as three tabs under the title. */
function ModelPage() {
  const { modelId } = Route.useParams()
  const { data: model } = useQuery(statisticalModelQuery(modelId))
  const { data: version } = useQuery(latestVersionQuery(modelId))
  if (!model || !version) return <p className="p-6 text-sm text-muted-foreground">Loading…</p>
  return (
    <div className="flex flex-col gap-6 p-4 md:p-6">
      <PageHeader
        type="model"
        title={model.name}
        below={
          <p className="text-xs text-muted-foreground">
            v{version.version} · immutable · {version.spec.sites.join(', ')}
          </p>
        }
      />
      <Tabs defaultValue="evaluation">
        <TabsList variant="line" className="w-full justify-start">
          <TabsTrigger value="card">Model card</TabsTrigger>
          <TabsTrigger value="evaluation">Evaluation</TabsTrigger>
          <TabsTrigger value="population">Population</TabsTrigger>
        </TabsList>
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
