import { useQuery } from '@tanstack/react-query'

import { fetchHealth, healthParts } from '@/lib/api'

export function SystemStatus() {
  const { data, error, isPending } = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 10_000,
  })

  if (isPending) {
    return <p className="text-sm text-neutral-500">Checking the system…</p>
  }
  if (error) {
    return (
      <p role="alert" className="text-sm text-red-600">
        The API cannot be reached.
      </p>
    )
  }
  return (
    <section aria-label="System status" className="rounded-lg border border-neutral-200 dark:border-neutral-800">
      <ul className="divide-y divide-neutral-200 dark:divide-neutral-800">
        {healthParts.map(({ key, label }) => (
          <li key={key} className="flex items-center justify-between px-4 py-2 text-sm">
            <span>{label}</span>
            <span
              className={
                data[key] === 'ok' ? 'text-green-700 dark:text-green-400' : 'text-red-600 dark:text-red-400'
              }
            >
              {data[key] === 'ok' ? 'OK' : 'Unavailable'}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}
