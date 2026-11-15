import { useEffect, useSyncExternalStore } from 'react'

import { currentToast, dismiss, subscribe } from '@/lib/toast'

/** The toast of the moment (`toast()` in lib/toast), at the bottom right. */
export function Toaster({ duration = 4000 }: { duration?: number }) {
  const shown = useSyncExternalStore(subscribe, currentToast)
  useEffect(() => {
    if (!shown) return
    const timer = setTimeout(() => dismiss(shown.id), duration)
    return () => clearTimeout(timer)
  }, [shown, duration])
  return (
    <div role="status" aria-live="polite" className="pointer-events-none fixed right-4 bottom-4 z-[60]">
      {shown && <p className="rounded-lg bg-foreground px-3.5 py-2.5 text-sm text-background shadow-lg">{shown.text}</p>}
    </div>
  )
}
