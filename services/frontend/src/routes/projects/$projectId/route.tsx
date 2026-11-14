import { createFileRoute, Link, Outlet, useMatches } from '@tanstack/react-router'

import { Hint } from '@/components/icon-action'
import { ConnectionIndicator, ProjectLive } from '@/components/live'
import { ProjectSidebar } from '@/components/project-sidebar'
import { ThemeToggle } from '@/components/theme-toggle'
import { AdaMark } from '@/components/vahti/vahti'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { WidgetModal } from '@/components/widget-modal'
import { pageOf } from '@/lib/page'

type Search = {
  /** A widget shown full size in a modal over the page (WidgetModal). */
  open?: string
}

// The layout of everything inside a project. It holds the project's live stream, so
// moving between the project, its sessions and its widgets keeps one connection.
export const Route = createFileRoute('/projects/$projectId')({
  // Every page of the project takes `?open=`, so a widget opens over whatever page it is on.
  validateSearch: (search: Record<string, unknown>): Search =>
    typeof search.open === 'string' && search.open !== '' ? { open: search.open } : {},
  component: ProjectLayout,
})

function ProjectLayout() {
  const { projectId } = Route.useParams()
  const { frozen } = pageOf(useMatches())

  return (
    <ProjectLive projectId={projectId}>
      <SidebarProvider>
        <ProjectSidebar projectId={projectId} />
        {/* The page scrolls inside, under a bar that stays: a session keeps its composer
            at the bottom, and a widget opened over a page leaves its scroll where it was. */}
        <SidebarInset className="h-svh overflow-hidden">
          <div className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
            <Hint label="Toggle the sidebar" side="right">
              <SidebarTrigger />
            </Hint>
            <Link to="/" aria-label="ADA: all projects" className="ml-1 rounded-md px-1 py-0.5 focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none">
              <AdaMark size={22} />
            </Link>
            <div className="flex-1" />
            {/* A frozen page never changes, so it says so itself instead of claiming "Live". */}
            {!frozen && <ConnectionIndicator />}
            <ThemeToggle />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto" data-page-scroll>
            <Outlet />
          </div>
        </SidebarInset>
        <WidgetModal projectId={projectId} />
      </SidebarProvider>
    </ProjectLive>
  )
}
