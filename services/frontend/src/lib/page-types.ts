import { Bell, ChartColumn, ClipboardList, Database, FileText, FolderKanban, LayoutDashboard, MessagesSquare, Settings, Sigma, type LucideIcon } from 'lucide-react'

/** The kinds of page in a project, each with the label and icon the sidebar uses too, so
 * the label above a page's title matches the group it was found in. */
export const pageTypes = {
  project: { label: 'Project', icon: FolderKanban },
  session: { label: 'Session', icon: MessagesSquare },
  dashboard: { label: 'Dashboard', icon: LayoutDashboard },
  report: { label: 'Report', icon: FileText },
  alerts: { label: 'Alerts', icon: Bell },
  case: { label: 'Case', icon: ClipboardList },
  model: { label: 'Model', icon: Sigma },
  source: { label: 'Data source', icon: Database },
  widget: { label: 'Widget', icon: ChartColumn },
  settings: { label: 'Settings', icon: Settings },
} satisfies Record<string, { label: string; icon: LucideIcon }>

export type PageTypeName = keyof typeof pageTypes
