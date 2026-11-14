import { createFileRoute } from '@tanstack/react-router'

import { SystemStatus } from '@/components/system-status'

export const Route = createFileRoute('/')({
  component: Home,
})

function Home() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-3xl font-semibold">Agentic data analysis</h1>
        <p className="mt-2 text-neutral-600 dark:text-neutral-400">
          Pipelines of operators over data sources, shown as widgets on dashboards and in reports.
        </p>
      </div>
      <SystemStatus />
    </div>
  )
}
