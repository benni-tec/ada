import { Bell, Globe, Workflow, type LucideIcon } from 'lucide-react'

import type { Attachment, AttachmentKind } from '@/lib/api'
import { pageTypes } from '@/lib/page-types'

/** Each kind's word and icon, the sidebar's where the sidebar has the kind. In the order
 * the Attach chooser lists them. */
export const attachmentKinds: Record<AttachmentKind, { label: string; plural: string; icon: LucideIcon }> = {
  dashboard: { label: 'Dashboard', plural: 'Dashboards', icon: pageTypes.dashboard.icon },
  report: { label: 'Report', plural: 'Reports', icon: pageTypes.report.icon },
  alert_rule: { label: 'Alert rule', plural: 'Alert rules', icon: Bell },
  source: { label: 'Data source', plural: 'Data sources', icon: pageTypes.source.icon },
  operator: { label: 'Pipeline', plural: 'Pipelines', icon: Workflow },
  session: { label: 'Session', plural: 'Sessions', icon: pageTypes.session.icon },
  widget: { label: 'Widget', plural: 'Widgets', icon: pageTypes.widget.icon },
  web_page: { label: 'Web page', plural: 'Web pages', icon: Globe },
}

/** The tab's words: the name it had when attached, else what kind of thing it is. */
export function attachmentTitle(attachment: Pick<Attachment, 'kind' | 'title'>): string {
  return attachment.title.trim() || attachmentKinds[attachment.kind].label
}
