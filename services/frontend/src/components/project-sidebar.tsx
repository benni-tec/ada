import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { Check, ChevronRight, ChevronsUpDown, LayoutGrid, Plus } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'

import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuBadge,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  SidebarRail,
  useSidebar,
} from '@/components/ui/sidebar'
import {
  alertFeedQuery,
  createDashboard,
  createSession,
  dashboardKeys,
  dashboardsQuery,
  keys,
  projectQuery,
  projectsQuery,
  reportsQuery,
  sessionsQuery,
  type Id,
} from '@/lib/api'
import { severityPillClasses, worstActive } from '@/components/alerts/labels'
import { pageTypes, type PageTypeName } from '@/lib/page-types'

import { CreateDialog } from './create-dialog'
import { Hint } from './icon-action'

/**
 * The project's navigation, after shadcn's sidebar that collapses to icons: the project
 * switcher in its header, then the overview and one collapsible item per type, listing
 * its items with a "new" action where there is one. The current page is marked
 * (`aria-current`), so the sidebar also says where one is, in place of breadcrumbs.
 */
export function ProjectSidebar({ projectId }: { projectId: Id }) {
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <ProjectSwitcher projectId={projectId} />
      </SidebarHeader>
      <SidebarContent>
        <nav aria-label="Project" className="contents">
          {/* What needs attention first, apart from the project's contents below. */}
          <SidebarGroup className="pb-0">
            <SidebarMenu>
              <Alerts projectId={projectId} />
            </SidebarMenu>
          </SidebarGroup>
          <SidebarGroup className="pt-4">
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild tooltip="Overview">
                  <Link to="/projects/$projectId" params={{ projectId }} activeOptions={{ exact: true, includeHash: false }} activeProps={{ 'data-active': true }}>
                    <LayoutGrid aria-hidden="true" />
                    <span>Overview</span>
                  </Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <Sessions projectId={projectId} />
              <Dashboards projectId={projectId} />
              <Reports projectId={projectId} />
            </SidebarMenu>
          </SidebarGroup>
        </nav>
      </SidebarContent>
      <SidebarFooter>
        <SettingsLink projectId={projectId} />
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}

/** The project's name, opening a menu of the other projects and the way to all of them. */
function ProjectSwitcher({ projectId }: { projectId: Id }) {
  const { isMobile } = useSidebar()
  const { data: project } = useQuery(projectQuery(projectId))
  const { data: projects } = useQuery(projectsQuery())
  const Icon = pageTypes.project.icon
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <SidebarMenuButton size="lg" aria-label={`Project ${project?.name ?? ''}: switch project`} className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground">
              <span className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                <Icon aria-hidden="true" className="size-4" />
              </span>
              <span className="grid flex-1 text-left leading-tight">
                <span className="text-xs text-sidebar-foreground/70">Project</span>
                <span className="truncate font-semibold">{project?.name ?? '…'}</span>
              </span>
              <ChevronsUpDown aria-hidden="true" className="ml-auto" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
            align="start"
            side={isMobile ? 'bottom' : 'right'}
            sideOffset={4}
          >
            <DropdownMenuLabel className="text-xs text-muted-foreground">Projects</DropdownMenuLabel>
            {projects?.map((other) => (
              <DropdownMenuItem key={other.id} asChild className="gap-2 p-2">
                <Link to="/projects/$projectId" params={{ projectId: other.id }}>
                  <span className="flex size-6 items-center justify-center rounded-md border">
                    <Icon aria-hidden="true" className="size-3.5 shrink-0" />
                  </span>
                  <span className="truncate">{other.name}</span>
                  {other.id === projectId && <Check aria-label="Current" className="ml-auto" />}
                </Link>
              </DropdownMenuItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild className="gap-2 p-2">
              <Link to="/">
                <span className="flex size-6 items-center justify-center rounded-md border bg-transparent">
                  <LayoutGrid aria-hidden="true" className="size-3.5" />
                </span>
                All projects
              </Link>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}

/**
 * One type: its icon and label, which fold its items away, a "new" action, and its items.
 * Collapsed to icons, the icon opens the sidebar instead, since the items cannot show.
 */
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
  const { state, setOpen: setSidebarOpen } = useSidebar()
  const [open, setOpen] = useState(true)
  const Icon = pageTypes[type].icon
  return (
    <Collapsible asChild open={open} onOpenChange={setOpen} className="group/collapsible">
      <SidebarMenuItem role="group" aria-labelledby={labelId}>
        <CollapsibleTrigger asChild>
          <SidebarMenuButton
            tooltip={label}
            onClick={(event) => {
              if (state !== 'collapsed') return
              event.preventDefault()
              setSidebarOpen(true)
              setOpen(true)
            }}
          >
            <Icon aria-hidden="true" />
            <span id={labelId}>{label}</span>
            <ChevronRight
              aria-hidden="true"
              className="ml-auto transition-transform duration-200 group-data-[state=open]/collapsible:rotate-90"
            />
          </SidebarMenuButton>
        </CollapsibleTrigger>
        {action}
        <CollapsibleContent>
          <SidebarMenuSub>{children}</SidebarMenuSub>
        </CollapsibleContent>
      </SidebarMenuItem>
    </Collapsible>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return <li className="px-2 py-1 text-xs text-sidebar-foreground/60">{children}</li>
}

/** One item of a type, as a link. */
function Item({ active, children }: { active?: boolean; children: ReactNode }) {
  return (
    <SidebarMenuSubItem>
      <SidebarMenuSubButton asChild isActive={active}>
        {children}
      </SidebarMenuSubButton>
    </SidebarMenuSubItem>
  )
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
            <SidebarMenuAction aria-label="New session">
              <Plus />
            </SidebarMenuAction>
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
        <Item key={session.id} active={session.id === sessionId}>
            <Link to="/projects/$projectId/sessions/$sessionId" params={{ projectId, sessionId: session.id }}>
              <span>{session.title}</span>
            </Link>
        </Item>
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
            <SidebarMenuAction aria-label="New dashboard">
              <Plus />
            </SidebarMenuAction>
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
        <Item key={dashboard.id} active={dashboard.id === dashboardId}>
            <Link to="/projects/$projectId/dashboards/$dashboardId" params={{ projectId, dashboardId: dashboard.id }}>
              <span>{dashboard.name}</span>
            </Link>
        </Item>
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
          <SidebarMenuAction asChild>
            <Link to="/projects/$projectId/reports/new" params={{ projectId }} aria-label="Generate a report">
              <Plus />
            </Link>
          </SidebarMenuAction>
        </Hint>
      }
    >
      {data && reports.length === 0 && <Empty>No reports yet.</Empty>}
      {reports.map((report) => (
        <Item key={report.id} active={report.id === reportId}>
            <Link to="/projects/$projectId/reports/$reportId" params={{ projectId, reportId: report.id }}>
              <span>{report.name}</span>
            </Link>
        </Item>
      ))}
    </Group>
  )
}

/** One page, not a list: the dashboards' rules and alerts, with the active alerts counted.
 * The count takes the colour of the most severe of them: red only once one is critical. */
function Alerts({ projectId }: { projectId: Id }) {
  const { data: firing } = useQuery(alertFeedQuery(projectId, 'firing'))
  const count = firing?.length ?? 0
  const worst = firing ? worstActive(firing) : null
  const Icon = pageTypes.alerts.icon
  return (
    <SidebarMenuItem>
      <SidebarMenuButton asChild tooltip={count > 0 ? `Alerts: ${count} active` : 'Alerts'}>
        <Link to="/projects/$projectId/alerts" params={{ projectId }} activeProps={{ 'data-active': true }}>
          <Icon aria-hidden="true" />
          <span>Alerts</span>
        </Link>
      </SidebarMenuButton>
      {count > 0 && worst && (
        <SidebarMenuBadge className={severityPillClasses[worst]} data-severity={worst}>
          {count}
          <span className="sr-only"> active</span>
        </SidebarMenuBadge>
      )}
    </SidebarMenuItem>
  )
}

/** Shared settings and the project's data sources, at the bottom of the sidebar. */
function SettingsLink({ projectId }: { projectId: Id }) {
  const Icon = pageTypes.settings.icon
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton asChild tooltip="Settings">
          <Link
            to="/projects/$projectId/settings"
            params={{ projectId }}
            activeOptions={{ includeHash: false }}
            activeProps={{ 'data-active': true }}
          >
            <Icon aria-hidden="true" />
            <span>Settings</span>
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
