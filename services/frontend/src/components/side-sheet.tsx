import { X } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'

import { Hint } from './icon-action'
import { useInertBehind } from './inert-behind'

/**
 * A wide sheet from the right, over the page: the same contract as Modal (its name from
 * the title, focus moved in to `data-autofocus` and back to the opener, the page behind
 * inert, Escape, × and a click outside to close), but the page stays in view at the left,
 * so what was clicked is still there to compare with.
 */
export function SideSheet({
  title,
  description,
  actions,
  onClose,
  children,
}: {
  title: ReactNode
  description?: ReactNode
  /** Icon actions in the header, left of the ×. */
  actions?: ReactNode
  onClose: () => void
  children: ReactNode
}) {
  const [content, setContent] = useState<HTMLDivElement | null>(null)
  useInertBehind(content)
  const [opener] = useState(() => (document.activeElement instanceof HTMLElement ? document.activeElement : null))

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent
        ref={setContent}
        side="right"
        showCloseButton={false}
        aria-modal="true"
        onCloseAutoFocus={(event) => {
          event.preventDefault()
          if (opener?.isConnected) opener.focus()
        }}
        onOpenAutoFocus={(event) => {
          event.preventDefault()
          const target = event.currentTarget as HTMLElement
          ;(target.querySelector<HTMLElement>('[data-autofocus]') ?? target).focus()
        }}
        className="gap-0 p-0 data-[side=right]:w-full data-[side=right]:sm:max-w-[min(80rem,calc(100vw-3rem))]"
      >
        <header className="flex items-start justify-between gap-4 border-b px-4 py-3">
          <div className="flex min-w-0 flex-col gap-0.5">
            <SheetTitle className="truncate text-base font-semibold">{title}</SheetTitle>
            {description ? (
              <SheetDescription asChild>
                <div className="text-xs">{description}</div>
              </SheetDescription>
            ) : (
              <SheetDescription className="sr-only" />
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {actions}
            <Hint label="Close">
              <SheetClose asChild>
                <Button variant="ghost" size="icon-sm" aria-label="Close">
                  <X />
                </Button>
              </SheetClose>
            </Hint>
          </div>
        </header>
        <div className="min-h-0 flex-1">{children}</div>
      </SheetContent>
    </Sheet>
  )
}
