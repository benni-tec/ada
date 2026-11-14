import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import {
  ApiFailure,
  dashboardKeys,
  dashboardRunQuery,
  errorMessage,
  getDashboard,
  type Dashboard,
  type DashboardTimeRange,
  type DashboardView,
  type Id,
} from '@/lib/api'
import { useViewRun } from '@/lib/view-run'

/**
 * The run a dashboard is viewed at: every widget on it reads this one, so the dashboard is
 * one consistent cut, and it follows the latest data (useViewRun).
 */
export function useDashboardRun(dashboardId: Id, range: DashboardTimeRange, enabled = true) {
  return useViewRun(dashboardRunQuery(dashboardId, range), dashboardKeys.allRuns(), enabled)
}

/**
 * A write to a dashboard, which carries a revision (optimistic locking). It is made on the
 * revision this page last showed, so an edit by someone else in between is refused with
 * a 409: the dashboard is then read again and `conflict` says so, instead of the write
 * silently replacing their version.
 */
export function useDashboardWrite(dashboardId: Id) {
  const queryClient = useQueryClient()
  const [conflict, setConflict] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: async (write: (dashboard: Dashboard) => Promise<DashboardView>) => {
      setConflict(null)
      const shown = queryClient.getQueryData<DashboardView>(dashboardKeys.view(dashboardId))
      const current = shown ?? (await getDashboard(dashboardId))
      return write(current.dashboard)
    },
    onSuccess: (saved) => {
      queryClient.setQueryData<DashboardView>(dashboardKeys.view(dashboardId), saved)
      void queryClient.invalidateQueries({ queryKey: dashboardKeys.versions(dashboardId) })
      void queryClient.invalidateQueries({ queryKey: dashboardKeys.list(saved.dashboard.project_id) })
    },
    onError: async (error) => {
      if (!(error instanceof ApiFailure && error.isConflict)) return
      await queryClient.invalidateQueries({ queryKey: dashboardKeys.view(dashboardId) })
      setConflict(
        'Someone else changed this dashboard while you were looking at it. It has been read again; ' +
          'check what it shows now and make your change again.',
      )
    },
  })

  const failed = mutation.error && !(mutation.error instanceof ApiFailure && mutation.error.isConflict)
  return {
    /** Resolves to whether the write was saved; a failure is in `conflict` or `error`. */
    write: (write: (dashboard: Dashboard) => Promise<DashboardView>) =>
      mutation.mutateAsync(write).then(
        () => true,
        () => false,
      ),
    pending: mutation.isPending,
    conflict,
    error: failed ? errorMessage(mutation.error) : null,
    dismissConflict: () => setConflict(null),
  }
}
