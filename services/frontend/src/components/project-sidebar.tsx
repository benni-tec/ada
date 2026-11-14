import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { ArrowLeft, CircleAlert, Plus } from 'lucide-react'
import { useId, type ReactNode } from 'react'

import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupAction,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from '@/components/ui/sidebar'
import {
  alertFeedQuery,
  createDashboard,
  createSession,
  dashboardKeys,
  dashboardsQuery,
  keys,
  projectQuery,
  reportsQuery,
  sessionsQuery,
  sourcesQuery,
  type Id,
} from '@/lib/api'
import { pageTypes, type PageTypeName } from '@/lib/page-types'

import { CreateDialog } from './create-dialog'
import { Hint } from './icon-action'

/**
 * The project's navigation: its name, the way back to all projects, and its groups, each
 * listing its items with a "new" action where there is one. The current page is marked
 * (`aria-current`), so the sidebar also says where one is, in place of breadcrumbs.
 */
export function ProjectSidebar({ projectId }: { projectId: Id }) {
  const { data: project } = useQuery(projectQuery(projectId))
  return (
    <Sidebar>
      <SidebarHeader className="gap-1">
        <Link
          to="/"
          className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-sidebar-foreground/70 hover:text-sidebar-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring focus-visible:outline-hidden"
        >
          <ArrowLeft aria-hidden="true" className="size-3.5" />
          All projects
        </Link>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton asChild size="lg">
              <Link to="/projects/$projectId" params={{ projectId }} activeOptions={{ exact: true, includeSearch: false }}>
                <span className="flex size-8 items-center justify-center rounded-md bg-sidebar-primary text-sidebar-primary-foreground">
                  <pageTypes.project.icon aria-hidden="true" className="size-4" />
                </span>
                <span className="flex min-w-0 flex-col">
                  <span className="text-xs text-sidebar-foreground/70">Project</span>
                  <span className="truncate font-semibold">{project?.name ?? '…'}</span>
                </span>
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <nav aria-label="Project" className="contents">
          <Sessions projectId={projectId} />
          <Dashboards projectId={projectId} />
          <Reports projectId={projectId} />
          <Alerts projectId={projectId} />
          <Sources projectId={projectId} />
        </nav>
      </SidebarContent>
      <SidebarRail />
    </Sidebar>
  )
}

/** One group: its label with the type's icon, a "new" action, and its items. */
function Group({
  type,
  label,
  action,
  children,
}: {
  type: PageTypeName
  label: string
  action?: ReactNode
  children: ReactNode
}) {
  const labelId = useId()
  const Icon = pageTypes[type].icon
  return (
    <SidebarGroup role="group" aria-labelledby={labelId}>
      <SidebarGroupLabel id={labelId} className="gap-2">
        <Icon aria-hidden="true" />
        {label}
      </SidebarGroupLabel>
      {action}
      <SidebarGroupContent>
        <SidebarMenu>{children}</SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return <li className="px-2 py-1 text-xs text-sidebar-foreground/60">{children}</li>
}

function Sessions({ projectId }: { projectId: Id }) {
  const { sessionId } = useParams({ strict: false })
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { data } = useQuery(sessionsQuery(projectId))
  const sessions = [...(data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at))
  return (
    <Group
      type="session"
      label="Sessions"
      action={
        <CreateDialog
          hint="New session"
          trigger={
            <SidebarGroupAction aria-label="New session">
              <Plus />
            </SidebarGroupAction>
          }
          title="New session"
          description="A session holds one line of questions: the conversation and what was made in it."
          field="Title"
          placeholder="The question to explore"
          submit="Start session"
          create={async (title) => {
            const session = await createSession(projectId, title)
            await queryClient.invalidateQueries({ queryKey: keys.sessions(projectId) })
            await navigate({ to: '/projects/$projectId/sessions/$sessionId', params: { projectId, sessionId: session.id } })
          }}
        />
      }
    >
      {data && sessions.length === 0 && <Empty>No sessions yet.</Empty>}
      {sessions.map((session) => (
        <SidebarMenuItem key={session.id}>
          <SidebarMenuButton asChild isActive={session.id === sessionId}>
            <Link to="/projects/$projectId/sessions/$sessionId" params={{ projectId, sessionId: session.id }}>
              <span>{session.title}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      ))}
    </Group>
  )
}

function Dashboards({ projectId }: { projectId: Id }) {
  const { dashboardId } = useParams({ strict: false })
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { data: dashboards } = useQuery(dashboardsQuery(projectId))
  return (
    <Group
      type="dashboard"
      label="Dashboards"
      action={
        <CreateDialog
          hint="New dashboard"
          trigger={
            <SidebarGroupAction aria-label="New dashboard">
              <Plus />
            </SidebarGroupAction>
          }
          title="New dashboard"
          description="A dashboard keeps widgets on a grid, all at one run of their data."
          field="Name"
          placeholder="What it keeps an eye on"
          submit="Create dashboard"
          create={async (name) => {
            const dashboard = await createDashboard(projectId, name)
            await queryClient.invalidateQueries({ queryKey: dashboardKeys.list(projectId) })
            await navigate({
              to: '/projects/$projectId/dashboards/$dashboardId',
              params: { projectId, dashboardId: dashboard.id },
            })
          }}
        />
      }
    >
      {dashboards?.length === 0 && <Empty>No dashboards yet.</Empty>}
      {dashboards?.map((dashboard) => (
        <SidebarMenuItem key={dashboard.id}>
          <SidebarMenuButton asChild isActive={dashboard.id === dashboardId}>
            <Link to="/projects/$projectId/dashboards/$dashboardId" params={{ projectId, dashboardId: dashboard.id }}>
              <span>{dashboard.name}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      ))}
    </Group>
  )
}

function Reports({ projectId }: { projectId: Id }) {
  const { reportId } = useParams({ strict: false })
  const { data } = useQuery(reportsQuery(projectId))
  const reports = [...(data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at))
  return (
    <Group
      type="report"
      label="Reports"
      action={
        <Hint label="Generate a report">
          <SidebarGroupAction asChild>
            <Link to="/projects/$projectId/reports/new" params={{ projectId }} aria-label="Generate a report">
              <Plus />
            </Link>
          </SidebarGroupAction>
        </Hint>
      }
    >
      {data && reports.length === 0 && <Empty>No reports yet.</Empty>}
      {reports.map((report) => (
        <SidebarMenuItem key={report.id}>
          <SidebarMenuButton asChild isActive={report.id === reportId}>
            <Link to="/projects/$projectId/reports/$reportId" params={{ projectId, reportId: report.id }}>
              <span>{report.name}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      ))}
    </Group>
  )
}

function Alerts({ projectId }: { projectId: Id }) {
  const { data: firing } = useQuery(alertFeedQuery(projectId, 'firing'))
  const count = firing?.length ?? 0
  return (
    <Group type="alerts" label="Alerts">
      <SidebarMenuItem>
        <SidebarMenuButton asChild>
          <Link to="/projects/$projectId/alerts" params={{ projectId }} activeProps={{ 'data-active': true }}>
            <span>Feed and rules</span>
          </Link>
        </SidebarMenuButton>
        {count > 0 && (
          <SidebarMenuBadge className="bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-200">
            {count}
            <span className="sr-only"> firing</span>
          </SidebarMenuBadge>
        )}
      </SidebarMenuItem>
    </Group>
  )
}

/** The sources have no page of their own: each leads to its card on the overview. */
function Sources({ projectId }: { projectId: Id }) {
  const { data: sources } = useQuery(sourcesQuery(projectId))
  return (
    <Group type="source" label="Data sources">
      {sources?.length === 0 && <Empty>None yet. Agents register them over MCP.</Empty>}
      {sources?.map((source) => (
        <SidebarMenuItem key={source.id}>
          <SidebarMenuButton asChild>
            <Link to="/projects/$projectId" params={{ projectId }} hash={`source-${source.id}`} activeOptions={{ exact: true, includeHash: true }}>
              <span>{source.name}</span>
            </Link>
          </SidebarMenuButton>
          {source.last_error && (
            <SidebarMenuBadge>
              <CircleAlert aria-label="Last refresh failed" className="size-3.5 text-amber-600 dark:text-amber-400" />
            </SidebarMenuBadge>
          )}
        </SidebarMenuItem>
      ))}
    </Group>
  )
}
