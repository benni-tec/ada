import type { ReactNode } from 'react'

import { pageTypes, type PageTypeName } from '@/lib/page-types'

/** The small label above a page's title saying what kind of page it is, with the icon the
 * sidebar uses for the same kind. It replaces the breadcrumbs. */
export function PageType({ type, children }: { type: PageTypeName; children?: ReactNode }) {
  const { label, icon: Icon } = pageTypes[type]
  return (
    <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground" data-page-type={type}>
      <Icon aria-hidden="true" className="size-3.5" />
      {children ?? label}
    </p>
  )
}

/**
 * A page's header: its type, its title (a heading, or an editable one), a line below and
 * actions at the right.
 */
export function PageHeader({
  type,
  typeLabel,
  title,
  below,
  actions,
}: {
  type: PageTypeName
  /** Instead of the type's own label, e.g. "New report". */
  typeLabel?: ReactNode
  /** The `<h1>`, or an EditableTitle. */
  title: ReactNode
  below?: ReactNode
  actions?: ReactNode
}) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
      <div className="flex min-w-0 flex-col gap-1">
        <PageType type={type}>{typeLabel}</PageType>
        {typeof title === 'string' ? <h1 className="text-2xl font-semibold break-words">{title}</h1> : title}
        {below}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}
