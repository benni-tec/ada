import { Link, type LinkComponentProps } from '@tanstack/react-router'
import { SquareArrowOutUpRight } from 'lucide-react'
import type { ReactNode } from 'react'

import { Hint } from '@/components/icon-action'
import { Button } from '@/components/ui/button'

/** The line above a tab's view: what it shows, in a few words, and the way to its page. */
export function ViewBar({ children, open }: { children: ReactNode; open?: ReactNode }) {
  return (
    <div className="flex min-h-7 items-center justify-between gap-3">
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">{children}</div>
      {open}
    </div>
  )
}

/** The thing's own page, as an icon whose tooltip is its name. */
export function OpenLink({ label, icon, ...link }: LinkComponentProps & { label: string; icon?: ReactNode }) {
  return (
    <Hint label={label}>
      <Button asChild variant="ghost" size="icon-sm" className="shrink-0">
        <Link {...link} aria-label={label}>
          {icon ?? <SquareArrowOutUpRight />}
        </Link>
      </Button>
    </Hint>
  )
}
