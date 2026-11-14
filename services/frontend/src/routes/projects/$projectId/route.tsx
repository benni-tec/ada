import { createFileRoute, Outlet, useMatches } from '@tanstack/react-router'

import { Hint } from '@/components/icon-action'
import { ConnectionIndicator, ProjectLive } from '@/components/live'
import { ProjectSidebar } from '@/components/project-sidebar'
import { SettingsModal } from '@/components/settings/settings-modal'
import { ThemeToggle } from '@/components/theme-toggle'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { WidgetModal } from '@/components/widget-modal'
import { pageOf } from '@/lib/page'
import { isSettingsSection, type SettingsSectionId } from '@/lib/settings-sections'

type Search = {
  /** A widget shown full size in a modal over the page (WidgetModal). */
  open?: string
  /** The settings, open at this section in a modal over the page (SettingsModal). */
  settings?: SettingsSectionId
}

// The layout of everything inside a project. It holds the project's live stream, so
// moving between the project, its sessions and its widgets keeps one connection.
export const Route = createFileRoute('/projects/$projectId')({
  // Every page of the project takes `?open=` and `?settings=`, so a widget or the settings
  // open over whatever page they are on. An unknown section is dropped.
  validateSearch: (search: Record<string, unknown>): Search => ({
    ...(typeof search.open === 'string' && search.open !== '' ? { open: search.open } : {}),
    ...(isSettingsSection(search.settings) ? { settings: search.settings } : {}),
  }),
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
        <SettingsModal projectId={projectId} />
      </SidebarProvider>
    </ProjectLive>
  )
}
