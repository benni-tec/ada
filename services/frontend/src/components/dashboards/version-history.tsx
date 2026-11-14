import { Link } from '@tanstack/react-router'

import { Provenance } from '@/components/provenance'
import type { Dashboard, DashboardVersion } from '@/lib/api'

/**
 * Every version of the dashboard, newest first. Each edit by a person or an agent added
 * one, so this is also the record of who changed what. A version can be looked at, and
 * restored: restoring adds a new version with the same slots, nothing is overwritten.
 */
export function VersionHistory({
  dashboard,
  versions,
  viewing,
  onRestore,
  restoring,
}: {
  dashboard: Dashboard
  versions: readonly DashboardVersion[]
  /** The version number being looked at, if not the current one. */
  viewing: number | undefined
  onRestore: (version: DashboardVersion) => void
  restoring: boolean
}) {
  if (versions.length === 0) return <p className="text-sm text-neutral-500">No versions yet: nothing has been pinned.</p>
  const newestFirst = [...versions].sort((a, b) => b.number - a.number)
  return (
    <ol aria-label="Version history" className="flex flex-col divide-y divide-neutral-200 dark:divide-neutral-800">
      {newestFirst.map((version) => {
        const current = version.id === dashboard.current_version_id
        const shown = current ? viewing === undefined : viewing === version.number
        return (
          <li key={version.id} className="flex flex-col gap-1 py-2 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">Version {version.number}</span>
              {current && (
                <span className="rounded bg-green-100 px-1.5 py-0.5 text-xs text-green-800 dark:bg-green-950 dark:text-green-200">
                  current
                </span>
              )}
              <span className="text-xs text-neutral-500">
                {version.slots.length} slot{version.slots.length === 1 ? '' : 's'}
              </span>
            </div>
            <Provenance actor={version.created_by} at={version.created_at} />
            <div className="flex gap-3 text-xs">
              {shown ? (
                <span aria-current="true" className="text-neutral-500">
                  Showing
                </span>
              ) : (
                <Link
                  to="/projects/$projectId/dashboards/$dashboardId"
                  params={{ projectId: dashboard.project_id, dashboardId: dashboard.id }}
                  search={current ? {} : { version: version.number }}
                  aria-label={`View version ${version.number}`}
                  className="text-blue-700 underline-offset-2 hover:underline dark:text-blue-400"
                >
                  View
                </Link>
              )}
              {!current && (
                <button
                  type="button"
                  disabled={restoring}
                  onClick={() => onRestore(version)}
                  aria-label={`Restore version ${version.number}`}
                  className="text-blue-700 underline-offset-2 hover:underline disabled:opacity-50 dark:text-blue-400"
                >
                  Restore
                </button>
              )}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
