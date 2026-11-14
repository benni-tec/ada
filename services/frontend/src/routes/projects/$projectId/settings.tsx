import { createFileRoute } from '@tanstack/react-router'

import { PageHeader } from '@/components/page-header'
import { AgentSettingsSection } from '@/components/settings/agents'
import { DataSourcesSection } from '@/components/settings/data-sources'

export const Route = createFileRoute('/projects/$projectId/settings')({
  component: SettingsPage,
})

/**
 * The agent, shared by all projects (providers, keys, models, the session agent), and this
 * project's data sources. Reached from the gear at the bottom of the sidebar.
 */
function SettingsPage() {
  const { projectId } = Route.useParams()
  return (
    <div className="flex max-w-5xl flex-col gap-10 p-4 md:p-6">
      <PageHeader type="settings" title="Settings" />
      <AgentSettingsSection />
      <DataSourcesSection projectId={projectId} />
    </div>
  )
}
