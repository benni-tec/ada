import { ago, clockTime, useNow } from '@/lib/clock'

/**
 * A moment to the second and how long ago it was, "14:02:11, 40 s ago", counting up while
 * shown: how fresh live data is, readable at a glance. `relative={false}` leaves out the
 * "ago", e.g. for the start of a span whose end carries it.
 */
export function LiveTime({ value, relative = true }: { value: string | number; relative?: boolean }) {
  const now = useNow()
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return <time>{String(value)}</time>
  return (
    <time dateTime={date.toISOString()} title={date.toLocaleString()} className="tabular-nums">
      {clockTime(date, new Date(now))}
      {relative && `, ${ago(date.getTime(), now)}`}
    </time>
  )
}
