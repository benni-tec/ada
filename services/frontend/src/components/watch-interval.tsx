import type { DataSource } from '@/lib/api'

/** Null means the existing monitor uses the server's configured interval. */
export function WatchInterval({ source }: { source: DataSource }) {
  if (!source.monitor_id) return null
  const labels = { '10min': 'every 10 min', hourly: 'hourly', daily: 'daily' }
  return <span> · checks {source.check_every ? labels[source.check_every] : 'at server default'}</span>
}
