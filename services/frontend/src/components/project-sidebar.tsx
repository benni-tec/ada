import { useMutation, useQuery, useQueryClient, type QueryKey } from '@tanstack/react-query'
import { Link, useNavigate, useParams, useSearch } from '@tanstack/react-router'
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
  errorMessage,
  keys,
  projectQuery,
  projectsQuery,
  reportKeys,
  reportsQuery,
  reorderDashboards,
  reorderReports,
  sessionsQuery,
  type Id,
  type Session,
} from '@/lib/api'
import { severityPillClasses, worstActive } from '@/components/alerts/labels'
import { pageTypes, type PageTypeName } from '@/lib/page-types'
import { defaultSettingsSection, withSettings } from '@/lib/settings-sections'

import { CreateDialog } from './create-dialog'
import { Hint } from './icon-action'
import { SortableList, type SortHandle, type SortItem } from './sortable-list'

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
              {/* Cases and the models that run on them. */}
              <Group type="pathway" label="Pathways">
                <PageLink to="/projects/$projectId/cases" projectId={projectId} type="case" label="Cases" />
                <PageLink to="/projects/$projectId/models" projectId={projectId} type="model" label="Models" />
              </Group>
            </SidebarMenu>
          </SidebarGroup>
        </nav>
      </SidebarContent>
      <SidebarFooter>
        <SettingsLink />
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
            <SidebarMenuButton size="lg" tooltip={project?.name ?? 'Project'} aria-label={`Project ${project?.name ?? ''}: switch project`} className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground">
              <span aria-hidden="true" className="flex aspect-square size-8 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-sidebar-accent font-semibold text-sidebar-accent-foreground">
                {project?.name ? Array.from(project.name)[0].toUpperCase() : <Icon />}
              </span>
              <span className="grid flex-1 text-left leading-tight group-data-[collapsible=icon]:hidden">
                <span className="text-xs text-sidebar-foreground/70">Project</span>
                <span className="truncate font-semibold">{project?.name ?? '…'}</span>
              </span>
              <ChevronsUpDown aria-hidden="true" className="ml-auto group-data-[collapsible=icon]:hidden" />
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

/** One item of a type, as a link; one that can be moved gets its list's `sort` props. */
function Item({
  active,
  sort,
  children,
}: {
  active?: boolean
  sort?: { item: SortItem; handle: SortHandle }
  children: ReactNode
}) {
  return (
    <SidebarMenuSubItem {...sort?.item}>
      <SidebarMenuSubButton asChild isActive={active} {...sort?.handle}>
        {children}
      </SidebarMenuSubButton>
    </SidebarMenuSubItem>
  )
}

/** A list people put in their own order: it changes at once here, and stays if the
 * server agrees; otherwise the list comes back as it was, with the reason. */
function useReorder<T extends { id: string }>(queryKey: QueryKey, reorder: (ids: Id[]) => Promise<T[]>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: reorder,
    onMutate: async (ids) => {
      await queryClient.cancelQueries({ queryKey })
      queryClient.setQueryData<T[]>(queryKey, (items) =>
        items ? ids.map((id) => items.find((item) => item.id === id)).filter((item) => item !== undefined) : items,
      )
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey }),
  })
}

function ReorderFailed({ error }: { error: unknown }) {
  return (
    <li role="alert" className="px-2 py-1 text-xs text-red-700 dark:text-red-400">
      Could not move it: {errorMessage(error)}
    </li>
  )
}

function Sessions({ projectId }: { projectId: Id }) {
  const { sessionId } = useParams({ strict: false })
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { data } = useQuery(sessionsQuery(projectId))
  const sessions = [...(data ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at))
  // Delegated sessions (research, analysis) hang under the session that delegated them.
  const known = new Set(sessions.map((session) => session.id))
  const byParent = new Map<string, Session[]>()
  for (const session of sessions) {
    const parent = session.parent_session_id ?? ''
    byParent.set(parent, [...(byParent.get(parent) ?? []), session])
  }
  const roots = sessions.filter((session) => !session.parent_session_id || !known.has(session.parent_session_id))
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
      {roots.map((session) => (
        <SessionNode key={session.id} session={session} byParent={byParent} projectId={projectId} activeId={sessionId} />
      ))}
    </Group>
  )
}

/** A session and, nested under it, the sessions it delegated. */
function SessionNode({
  session,
  byParent,
  projectId,
  activeId,
}: {
  session: Session
  byParent: Map<string, Session[]>
  projectId: Id
  activeId: string | undefined
}) {
  const nested = byParent.get(session.id) ?? []
  return (
    <SidebarMenuSubItem>
      <SidebarMenuSubButton asChild isActive={session.id === activeId}>
        <Link to="/projects/$projectId/sessions/$sessionId" params={{ projectId, sessionId: session.id }}>
          <span>{session.title}</span>
          {session.agent !== 'session' && (
            <span className="ml-auto rounded-full border px-1.5 text-[10px] font-medium text-sidebar-foreground/70">
              {session.agent}
            </span>
          )}
        </Link>
      </SidebarMenuSubButton>
      {nested.length > 0 && (
        <SidebarMenuSub className="mx-0 pr-0">
          {nested.map((child) => (
            <SessionNode key={child.id} session={child} byParent={byParent} projectId={projectId} activeId={activeId} />
          ))}
        </SidebarMenuSub>
      )}
    </SidebarMenuSubItem>
  )
}

function Dashboards({ projectId }: { projectId: Id }) {
  const { dashboardId } = useParams({ strict: false })
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { data: dashboards } = useQuery(dashboardsQuery(projectId))
  const reorder = useReorder(dashboardKeys.list(projectId), (ids) => reorderDashboards(projectId, ids))
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
      <SortableList items={dashboards ?? []} label={(dashboard) => dashboard.name} onReorder={(ids) => reorder.mutate(ids)}>
        {(dashboard, sort) => (
          <Item active={dashboard.id === dashboardId} sort={sort}>
            <Link to="/projects/$projectId/dashboards/$dashboardId" params={{ projectId, dashboardId: dashboard.id }}>
              <span>{dashboard.name}</span>
            </Link>
          </Item>
        )}
      </SortableList>
      {reorder.isError && <ReorderFailed error={reorder.error} />}
    </Group>
  )
}

function Reports({ projectId }: { projectId: Id }) {
  const { reportId } = useParams({ strict: false })
  // In the order people gave them; new ones last.
  const { data: reports } = useQuery(reportsQuery(projectId))
  const reorder = useReorder(reportKeys.reports(projectId), (ids) => reorderReports(projectId, ids))
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
      {reports?.length === 0 && <Empty>No reports yet.</Empty>}
      <SortableList items={reports ?? []} label={(report) => report.name} onReorder={(ids) => reorder.mutate(ids)}>
        {(report, sort) => (
          <Item active={report.id === reportId} sort={sort}>
            <Link to="/projects/$projectId/reports/$reportId" params={{ projectId, reportId: report.id }}>
              <span>{report.name}</span>
            </Link>
          </Item>
        )}
      </SortableList>
      {reorder.isError && <ReorderFailed error={reorder.error} />}
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

/** One page of the project, as a link that is marked while one is on it or below it. */
function PageLink({
  to,
  projectId,
  type,
  label,
}: {
  to: '/projects/$projectId/cases' | '/projects/$projectId/models'
  projectId: Id
  type: PageTypeName
  label: string
}) {
  const Icon = pageTypes[type].icon
  return (
    <SidebarMenuSubItem>
      <SidebarMenuSubButton asChild>
        <Link to={to} params={{ projectId }} activeProps={{ 'data-active': true }}>
          <Icon aria-hidden="true" />
          <span>{label}</span>
        </Link>
      </SidebarMenuSubButton>
    </SidebarMenuSubItem>
  )
}

/** Shared settings and the project's, at the bottom of the sidebar: a modal over the page
 * (`?settings=`), marked while it is open. */
function SettingsLink() {
  const Icon = pageTypes.settings.icon
  const open = useSearch({ strict: false, select: (search) => search.settings !== undefined })
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton asChild tooltip="Settings">
          <Link
            to="."
            search={withSettings(defaultSettingsSection)}
            resetScroll={false}
            activeOptions={{ exact: true, includeSearch: true }}
            data-active={open || undefined}
          >
            <Icon aria-hidden="true" />
            <span>Settings</span>
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
