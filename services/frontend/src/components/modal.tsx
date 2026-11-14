import { X } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'

import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'

import { Hint } from './icon-action'

/**
 * A large modal dialog over the page, on shadcn's Dialog (Radix), which gives it:
 *
 * - its name from the title, and its description when given;
 * - focus moved in (to the element marked `data-autofocus`, else the dialog), Tab
 *   and Shift+Tab kept inside, and on closing focus back where it came from;
 * - Escape, the × and a click outside to close.
 *
 * Radix hides the page from screen readers (`aria-hidden`); the page is also made
 * `inert` here, so nothing behind can be reached at all while the dialog is open, as the
 * hand-made modal this replaces did.
 */
export function Modal({
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
  // A state, not a ref: Radix mounts the portal a render later, and the effect needs it.
  const [content, setContent] = useState<HTMLDivElement | null>(null)
  useInertBehind(content)
  // Where the focus was when it opened. Radix gives the focus back to a DialogTrigger;
  // these dialogs are opened by plain buttons and links, so it is given back here.
  const [opener] = useState(() => (document.activeElement instanceof HTMLElement ? document.activeElement : null))

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        ref={setContent}
        showCloseButton={false}
        // Radix hides the page from assistive technology instead; say it outright too.
        aria-modal="true"
        onCloseAutoFocus={(event) => {
          event.preventDefault()
          if (opener?.isConnected) opener.focus()
        }}
        onOpenAutoFocus={(event) => {
          // The element marked `data-autofocus`, else the dialog itself (its title is read
          // out): the first control would be an icon whose tooltip then opens on its own,
          // and the first Escape would close only that tooltip.
          event.preventDefault()
          const target = event.currentTarget as HTMLElement
          ;(target.querySelector<HTMLElement>('[data-autofocus]') ?? target).focus()
        }}
        className="flex h-[calc(100svh-1rem)] w-[calc(100vw-1rem)] max-w-[96rem] flex-col gap-0 overflow-hidden p-0 sm:h-[calc(100svh-2rem)] sm:max-w-[min(96rem,calc(100vw-2rem))] lg:h-[calc(100svh-3rem)]"
      >
        <header className="flex items-start justify-between gap-4 border-b px-4 py-3">
          <div className="flex min-w-0 flex-col gap-0.5">
            <DialogTitle className="truncate text-base font-semibold">{title}</DialogTitle>
            {description ? (
              <DialogDescription asChild>
                <div className="text-xs">{description}</div>
              </DialogDescription>
            ) : (
              // Radix asks for a description; an empty one is announced as nothing.
              <DialogDescription className="sr-only" />
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {actions}
            <Hint label="Close">
              <DialogClose asChild>
                <Button variant="ghost" size="icon-sm" aria-label="Close">
                  <X />
                </Button>
              </DialogClose>
            </Hint>
          </div>
        </header>
        <div className="min-h-0 flex-1">{children}</div>
      </DialogContent>
    </Dialog>
  )
}

/** Makes everything outside the dialog's layer `inert` while it is open. Layers opened
 * later (a tooltip, a dialog on top) are new children of <body> and stay reachable. */
function useInertBehind(dialog: HTMLElement | null) {
  useEffect(() => {
    if (!dialog) return
    const others = [...document.body.children].filter(
      (element): element is HTMLElement =>
        element instanceof HTMLElement &&
        !element.contains(dialog) &&
        element.getAttribute('data-slot') !== 'dialog-overlay' &&
        !element.hasAttribute('inert'),
    )
    for (const element of others) element.setAttribute('inert', '')
    return () => {
      for (const element of others) element.removeAttribute('inert')
    }
  }, [dialog])
}
