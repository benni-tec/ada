// One short message at a time, shown by the Toaster and gone after a few seconds, e.g.
// after a save that moved to another page. It lives outside React's tree, so it survives
// the navigation.

export type Toast = { id: number; text: string }

let current: Toast | null = null
let next = 1
const listeners = new Set<() => void>()

function publish(toast: Toast | null) {
  current = toast
  for (const listener of listeners) listener()
}

/** Shows `text` until the next one, or for a few seconds. */
export function toast(text: string) {
  publish({ id: next++, text })
}

/** Hides the toast `id` unless another one has replaced it. */
export function dismiss(id: number) {
  if (current?.id === id) publish(null)
}

export function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export const currentToast = () => current
