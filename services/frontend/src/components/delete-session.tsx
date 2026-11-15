import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Trash2 } from 'lucide-react'
import { useState } from 'react'

import { IconButton } from '@/components/icon-action'
import { ErrorNotice } from '@/components/notices'
import { Button } from '@/components/ui/button'
import { deleteSession, keys, reportsQuery, type Id } from '@/lib/api'

/** The way to delete a session: a trash icon beside its title, then a confirmation that
 * says what goes with it (its messages, agent turns and the reports it made) and what stays
 * (its widgets). After deleting, the project's overview. */
export function DeleteSession({ projectId, sessionId, title }: { projectId: Id; sessionId: Id; title: string }) {
  const [confirming, setConfirming] = useState(false)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const reports = useQuery({ ...reportsQuery(projectId), enabled: confirming })
  const owned = (reports.data ?? []).filter((report) => report.session_id === sessionId).length
  // Until the reports are counted the confirmation cannot say what goes, so Delete waits;
  // when they cannot be counted it says so rather than counting none.
  const counting = reports.isPending
  const made = reports.isError
    ? ', and any reports it made (they could not be counted)'
    : owned > 0
      ? `, and the ${owned === 1 ? 'report' : `${owned} reports`} it made`
      : ''
  const remove = useMutation({
    mutationFn: () => deleteSession(sessionId),
    onSuccess: async () => {
      queryClient.removeQueries({ queryKey: keys.session(sessionId) })
      // The lists refetch in the background: a slow one must not keep the page open.
      void queryClient.invalidateQueries({ queryKey: keys.sessions(projectId) })
      void queryClient.invalidateQueries({ queryKey: ['projects', projectId, 'reports'] })
      await navigate({ to: '/projects/$projectId', params: { projectId } })
    },
  })

  if (!confirming)
    return (
      <IconButton label="Delete the session" onClick={() => setConfirming(true)}>
        <Trash2 />
      </IconButton>
    )
  return (
    <div role="group" aria-label={`Delete ${title}?`} className="flex basis-full flex-col gap-2 rounded-md border border-destructive/40 p-3 text-sm">
      <p>
        Delete <strong>{title}</strong> with its messages and agent turns
        {counting ? ', and the reports it made (counting…)' : made}? Its widgets stay in the project.
      </p>
      <div className="flex gap-2">
        <Button variant="destructive" size="sm" disabled={counting || remove.isPending} onClick={() => remove.mutate()}>
          Delete
        </Button>
        <Button variant="outline" size="sm" disabled={remove.isPending} onClick={() => setConfirming(false)}>
          Cancel
        </Button>
      </div>
      {remove.error && <ErrorNotice error={remove.error} prefix="Not deleted:" />}
    </div>
  )
}
