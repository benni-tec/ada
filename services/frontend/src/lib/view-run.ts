import { useQuery, useQueryClient, type QueryKey, type UseQueryOptions } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

import { projectRunQuery, runKeys, type Id, type ReportSource, type Run } from '@/lib/api'
import { useLive } from '@/lib/live'

/**
 * The run a widget card is viewed at, which its frame and its pipeline's preview both
 * read, so the numbers in the preview are the ones on the card. The page decides it: one
 * run per view, never one per frame, and never one the preview starts by itself.
 */
export type CardRun = {
  /** Null while the page is starting it. */
  id: Id | null
  /** Pinned for good (a report, a run named in the address) rather than following the
   * data, which starts a new run when it changes. */
  frozen: boolean
  /** Which run this is, for the line above the preview: "report version 1.1.0", "The
   * dashboard's current run". */
  what: string
  /** The sources as a report version recorded them, address included; elsewhere the
   * project's sources as they are now. */
  sources?: readonly ReportSource[]
}

/**
 * The run a page is viewed at: started once and kept, every widget on the page reads it.
 * Changed source data makes it stale (the widgets would reload at the same moment), so a
 * new run is started and the page follows the latest data; the frames reload by their new
 * address. `stale` is the key prefix made stale then: all such runs, so a range or page
 * left earlier does not come back to an old run either. `enabled` is false until what the
 * run is for is known: a run for the wrong range would be wasted.
 */
export function useViewRun<Key extends QueryKey>(
  options: UseQueryOptions<Run, Error, Run, Key>,
  stale: QueryKey,
  enabled = true,
) {
  const queryClient = useQueryClient()
  const { widgetEpoch } = useLive()
  const seen = useRef(widgetEpoch)
  const staleKey = JSON.stringify(stale)
  useEffect(() => {
    if (seen.current === widgetEpoch) return
    seen.current = widgetEpoch
    void queryClient.invalidateQueries({ queryKey: JSON.parse(staleKey) as QueryKey })
  }, [widgetEpoch, queryClient, staleKey])
  return useQuery({ ...options, enabled })
}

/** One run for a session or a widget page: the whole of every source, no time range. */
export function useProjectRun(projectId: Id, enabled = true) {
  return useViewRun(projectRunQuery(projectId), runKeys.views(), enabled)
}
