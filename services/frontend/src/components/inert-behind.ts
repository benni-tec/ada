import { useEffect } from 'react'

/** Makes everything outside the dialog's layer `inert` while it is open. Layers opened
 * later (a tooltip, a dialog on top) are new children of <body> and stay reachable. */
export function useInertBehind(dialog: HTMLElement | null) {
  useEffect(() => {
    if (!dialog) return
    const others = [...document.body.children].filter(
      (element): element is HTMLElement =>
        element instanceof HTMLElement &&
        !element.contains(dialog) &&
        !['dialog-overlay', 'sheet-overlay'].includes(element.getAttribute('data-slot') ?? '') &&
        !element.hasAttribute('inert'),
    )
    for (const element of others) element.setAttribute('inert', '')
    return () => {
      for (const element of others) element.removeAttribute('inert')
    }
  }, [dialog])
}
