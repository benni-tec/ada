import { useQuery } from '@tanstack/react-query'
import { createFileRoute, Link, Outlet } from '@tanstack/react-router'

import { ConnectionIndicator, ProjectLive } from '@/components/live'
import { projectQuery } from '@/lib/api'

// The layout of everything inside a project. It holds the project's live stream, so
// moving between the project, its sessions and its widgets keeps one connection.
export const Route = createFileRoute('/projects/$projectId')({
  component: ProjectLayout,
})

function ProjectLayout() {
  const { projectId } = Route.useParams()
  const { data: project } = useQuery(projectQuery(projectId))

  return (
    <ProjectLive projectId={projectId}>
      <div className="flex flex-col gap-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <nav aria-label="Breadcrumb" className="text-sm text-neutral-600 dark:text-neutral-400">
            <ol className="flex flex-wrap items-center gap-1">
              <li>
                <Link to="/" className="hover:underline">
                  Projects
                </Link>
              </li>
              <li aria-hidden="true">/</li>
              <li>
                <Link
                  to="/projects/$projectId"
                  params={{ projectId }}
                  activeOptions={{ exact: true }}
                  activeProps={{ 'aria-current': 'page' }}
                  className="hover:underline"
                >
                  {project?.name ?? 'Project'}
                </Link>
              </li>
            </ol>
          </nav>
          <ConnectionIndicator />
        </div>
        <Outlet />
      </div>
    </ProjectLive>
  )
}
