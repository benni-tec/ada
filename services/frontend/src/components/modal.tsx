import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

const focusable = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function focusablesIn(root: HTMLElement): HTMLElement[] {
  return [...root.querySelectorAll<HTMLElement>(focusable)].filter((element) => !element.closest('[inert]'))
}

/**
 * A modal dialog over the page. Written out rather than a native `<dialog>`, whose modal
 * behaviour jsdom lacks, so the tests can check it:
 *
 * - labelled by its title, and described by `description` when given;
 * - focus moves in (to the element marked `data-autofocus`, else the first control), Tab
 *   and Shift+Tab cycle inside it, and on closing focus returns to where it came from;
 * - the page behind is `inert`, so neither the keyboard nor a screen reader reaches it;
 * - Escape, the close button and a click on the backdrop close it.
 */
export function Modal({
  title,
  description,
  onClose,
  children,
}: {
  title: ReactNode
  description?: ReactNode
  onClose: () => void
  children: ReactNode
}) {
  const titleId = useId()
  const descriptionId = useId()
  const panel = useRef<HTMLDivElement>(null)
  const layer = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null
    // Everything else on the page goes inert while the dialog is open.
    const others = [...document.body.children].filter(
      (element): element is HTMLElement =>
        element instanceof HTMLElement && element !== layer.current && !element.hasAttribute('inert'),
    )
    for (const element of others) element.setAttribute('inert', '')
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    const root = panel.current
    if (root) (root.querySelector<HTMLElement>('[data-autofocus]') ?? focusablesIn(root)[0] ?? root).focus()

    return () => {
      for (const element of others) element.removeAttribute('inert')
      document.body.style.overflow = overflow
      if (opener?.isConnected) opener.focus()
    }
  }, [])

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.stopPropagation()
      onClose()
      return
    }
    if (event.key !== 'Tab' || !panel.current) return
    const items = focusablesIn(panel.current)
    if (items.length === 0) {
      event.preventDefault()
      return
    }
    const [first, last] = [items[0], items[items.length - 1]]
    const active = document.activeElement
    const inside = active instanceof Node && panel.current.contains(active)
    if (event.shiftKey && (active === first || !inside)) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && (active === last || !inside)) {
      event.preventDefault()
      first.focus()
    }
  }

  return createPortal(
    <div
      ref={layer}
      className="fixed inset-0 z-50 flex items-stretch justify-center bg-neutral-950/50 p-2 sm:p-4 lg:p-6 dark:bg-black/70"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        onKeyDown={onKeyDown}
        className="flex w-full max-w-[96rem] min-w-0 flex-col overflow-hidden rounded-lg border border-neutral-200 bg-white text-neutral-900 shadow-xl outline-none dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100"
      >
        <header className="flex items-start justify-between gap-4 border-b border-neutral-200 px-4 py-3 dark:border-neutral-800">
          <div className="flex min-w-0 flex-col gap-0.5">
            <h2 id={titleId} className="truncate text-base font-semibold">
              {title}
            </h2>
            {description && (
              <div id={descriptionId} className="text-xs text-neutral-600 dark:text-neutral-400">
                {description}
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-md border border-neutral-300 px-2.5 py-1 text-sm font-medium hover:bg-neutral-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 dark:border-neutral-700 dark:hover:bg-neutral-800"
          >
            Close
          </button>
        </header>
        <div className="min-h-0 flex-1">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
