import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

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
import { useLive } from '@/lib/live'

/**
 * The run a dashboard is viewed at: every widget on it reads this one, so the dashboard is
 * one consistent cut. Changed source data makes the run stale (the widgets reload at the
 * same moment), and a new run is started so the dashboard follows the latest data.
 * `enabled` is false until the range is known: a run for the wrong range would be wasted.
 */
export function useDashboardRun(dashboardId: Id, range: DashboardTimeRange, enabled = true) {
  const queryClient = useQueryClient()
  const { widgetEpoch } = useLive()
  const seen = useRef(widgetEpoch)
  useEffect(() => {
    if (seen.current === widgetEpoch) return
    seen.current = widgetEpoch
    void queryClient.invalidateQueries({ queryKey: dashboardKeys.allRuns() })
  }, [widgetEpoch, queryClient])
  return useQuery({ ...dashboardRunQuery(dashboardId, range), enabled })
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
