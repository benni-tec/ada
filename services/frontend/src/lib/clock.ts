import { useEffect, useState } from 'react'

/** How long ago, in its largest whole unit: "40 s ago", "3 min ago", "2 h ago", "5 d ago".
 * A time ahead of the clock (a skewed server) counts as now. */
export function ago(then: number, now: number): string {
  const seconds = Math.max(0, Math.floor((now - then) / 1000))
  if (seconds < 60) return `${seconds} s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  return `${Math.floor(hours / 24)} d ago`
}

/** The time to the second, "14:02:11"; with its date first when that is not today. */
export function clockTime(date: Date, now: Date): string {
  const time = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  if (date.toDateString() === now.toDateString()) return time
  return `${date.toLocaleDateString(undefined, { dateStyle: 'medium' })} ${time}`
}

/** The current time, updated every second while the component is shown. */
export function useNow(): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  return now
}
